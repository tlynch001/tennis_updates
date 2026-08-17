# wta-daily

Automated, unattended generation of the **assets** for a daily YouTube video
covering the WTA Top N women's tennis rankings: rankings + movement, each
player's latest match, a narration script, broadcast-style graphics, and
(optionally) AI narration and a finished MP4. **Nothing is ever uploaded to
YouTube automatically** - this project stops at "ready for you to review,"
by design.

Built as a proper, installable Python package with a **plugin architecture**:
every external dependency (rankings data, match data, narration script
writing, voice synthesis, video assembly) sits behind a small abstract
interface and is looked up by name from a single YAML config file. Adding an
ATP feed, a "Top 25" variant, or a Spanish-language narrator is a matter of
writing one new module, not rewriting the pipeline. See
["Architecture & extending it"](#architecture--extending-it) below.

This repository currently implements **Phase 1** end-to-end (rankings ->
movement -> matches -> `report.json` -> `script.txt` -> `leaderboard.png` ->
`player_cards/*.png`) plus working, opt-in Phase 2 building blocks (ElevenLabs
narration, ffmpeg video assembly, git automation) that are disabled by
default. See ["Roadmap"](#roadmap) for what's next.

---

## Table of contents

- [Data source research & recommendation](#data-source-research--recommendation)
- [Understanding & optimizing API usage](#understanding--optimizing-api-usage)
- [Featured player (recurring editorial segment)](#featured-player-recurring-editorial-segment)
- [Narration pronunciation (ElevenLabs)](#narration-pronunciation-elevenlabs)
- [Player imagery: legal approach](#player-imagery-legal-approach)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Folder structure](#folder-structure)
- [Architecture & extending it](#architecture--extending-it)
- [Error handling & logging](#error-handling--logging)
- [Scheduling](#scheduling)
- [Raspberry Pi deployment](#raspberry-pi-deployment)
- [Testing & code quality](#testing--code-quality)
- [Roadmap](#roadmap)

---

## Data source research & recommendation

The brief asked for research into legal data sources before writing any
code, since scraping is off the table for anything that prohibits it.
Here's what was evaluated:

| Source | Verdict | Notes |
| --- | --- | --- |
| **`api.wtatennis.com` (used by this project)** | ✅ Selected (rankings, and one of two match sources) | The WTA's own public JSON backend - the same API that powers wtatennis.com. Confirmed live: no API key, no auth header, no `Origin`/`Referer` gate, and `wtatennis.com/robots.txt` returns `Disallow:` (empty) - automated access is not blocked. It's plain JSON over HTTPS, not HTML scraping. |
| Sackmann/Tennis Abstract GitHub data (`tennis_wta`) | ❌ Not used for daily data | Excellent, openly-hosted historical rankings/results, but licensed **CC BY-NC-SA 4.0 (non-commercial only)** and updated on the maintainer's own schedule (not guaranteed same-day), so it doesn't fit an unattended *daily*, potentially monetized YouTube pipeline. |
| **Stats Perform / Opta** | 🔒 The genuine, exclusive official WTA data partner (contract runs through 2030) | **No self-serve tier at all** - developer-portal registration is disabled; enterprise/contact-sales only, no public pricing (third-party estimates start around €250+/mo). Unrealistic for a hobby/unattended daily job. |
| **Genius Sports** | 🔒 Official for WTA/Australian Open, via a Stats Perform sub-license | Same access story as Stats Perform - enterprise only, no public pricing. |
| **Sportradar** | 🔒 Exclusive rights partner for **ATP** (not WTA); its WTA coverage is secondary/aggregated | Has a genuine 30-day/1,000-request self-serve trial, but production pricing reverts to sales (one estimate: "from $1,250/mo"). |
| **`livetennisapi.com` (used by this project, combined with `wta_official`)** | ✅ Selected as a second match-data source | Independent, **not** WTA-licensed, self-serve, publicly priced ($9.99-$99.99/mo tiers, 14-day-equivalent free tier). Genuine per-match `scheduled_time` + `event_status` (no tournament-date ambiguity), usually fresher than the free feed - but empirically has its own per-player coverage gaps (see below), so it's combined with `wta_official` via `best_of` rather than trusted alone. |
| **`api-tennis.com` (implemented, not enabled by default)** | ✅ Implemented as an available `best_of` source | Independent, **not** WTA-licensed, self-serve trial. Rankings matched `api.wtatennis.com` exactly; match coverage was *better* than `livetennisapi.com` for at least one player - but ~40% of a live sample showed match dates one calendar day later than the same matches' independently-confirmed dates. See "A second paid source evaluated" below for the full writeup on why this keeps it out of the default source list. |
| GoalServe, other RapidAPI tennis aggregators (`tennis-api.com`, "Ultimate Tennis", "Tennis Live Data") | 🔒 Good paid fallbacks, not currently wired in | Similar shape to the two above - self-serve, $10-$170/mo range, "real-time" marketing claims not independently verified for all of them. Reasonable alternatives/additions to the `best_of` source list (`wta_daily/plugins/matches/`) if the two implemented paid sources ever become unreliable. |
| SportsDataIO, Sportmonks, Enet Pulse, BetsAPI/B365api | ❌ Ruled out | SportsDataIO's only self-serve tier explicitly excludes tennis (full tennis access is enterprise-only); Sportmonks has no tennis product at all; Enet Pulse has no public pricing (sales-team engagement required even to trial); BetsAPI repackages bookmaker in-play data (polling-only, no push feed) rather than a league-sanctioned feed. |
| UTR (Universal Tennis Rating) Engage API | ❌ Ruled out | A *different* ranking system, not the official WTA ranking, and its terms explicitly bar analytics/derivative use of the data. |
| Scraping `wtatennis.com` HTML pages directly | ❌ Rejected | Unnecessary - the JSON API above is faster, more stable, and was confirmed reachable without scraping any HTML. |
| ESPN/Sofascore/other unofficial "hidden" APIs | ❌ Rejected | Similar shape to the WTA's own API but with murkier terms of use and no official relationship to the data. No reason to use a third party's undocumented endpoint when the primary source's own undocumented endpoint is available and unrestricted. |

Every independent aggregator's terms reviewed use similar boilerplate: data
is provided "as is," with no license granted for publication/broadcast -
narrating factual outcomes (scores, dates, rounds) in a video is generally
lower-risk than redistributing a raw feed, but none of them affirmatively
clear "narrate this in a monetized YouTube video." Treat that as a gray
area to be aware of, same as the free WTA endpoint's own undocumented-API
caveat below.

**Recommendation, and what's implemented:** use the WTA's own
`api.wtatennis.com` backend as the rankings provider
(`wta_daily/plugins/rankings/wta_official.py`) - it is official, free,
returns structured JSON, and `robots.txt` does not disallow it. For match
results, use it **combined with** a second, paid, self-serve source
(`wta_daily/plugins/matches/live_tennis_api.py`, `livetennisapi.com`) via a
`best_of` composite provider (`wta_daily/plugins/matches/best_of.py`) that
always keeps whichever source's result has the more recently confirmed
date - see "Match-data reliability" below for why relying on either source
alone isn't good enough in practice. The one caveat that still applies to
`api.wtatennis.com` - documented here and in the code - is that the WTA has
not published a formal developer contract or terms of service for this
specific endpoint, so it could change or introduce rate limiting without
notice. That risk (and the paid source's own coverage gaps) is exactly why
every provider sits behind the `RankingsProvider`/`MatchProvider`
interfaces: swapping to, or adding, another paid/contractually-licensed
provider later is a matter of adding one new plugin module and changing a
few lines in `config.yaml` - never a rewrite. A fully offline `sample`
provider (`wta_daily/plugins/rankings/sample.py`,
`wta_daily/plugins/matches/sample.py`, backed by fixtures in
`data/sample/`) is also included for development, tests, and demos.

### Match-data reliability (production incident, August 2026)

The first production run exposed two real bugs in `wta_official`'s match
provider, both now fixed and covered by
[`tests/test_wta_official_match_provider.py`](tests/test_wta_official_match_provider.py):

1. **Tournament start date reported as the match date.** `GET
   /players/{id}/matches` returns one `StartDate` (and `tournament.startDate`)
   value per *tournament*, repeated identically for every round played in
   it - there is no genuine per-match date anywhere in that response. The
   fix: for each candidate result, a second call to
   `GET /tournaments/{groupId}/{year}/matches` (which does carry a real
   per-fixture `MatchTimeStamp` and a `MatchState`) is used to recover the
   actual date, matching the fixture by the pair of player IDs. If that
   lookup can't confirm a date for any reason, `match_date` is `null` -
   **never** a tournament date. This second endpoint's results are cached
   per tournament for the life of one pipeline run, since several Top N
   players are usually in the same recent event.
2. **Stale player-match history.** That same per-player endpoint can lag
   real-world results by more than a week during/right after a tournament.
   Its `sort=desc` ordering of *what it does have* checks out (verified by
   comparing several players' results against the tournament's own live
   scores), so it's still used to identify "the most recent result this
   endpoint knows about" - but there's no cheap way to independently
   discover "what tournaments are happening right now" from this API (the
   tournament list endpoint returns its full ~19,000-entry history back to
   1960 with no working date/status filter) to double check that. Building
   a speculative live-event scanner was judged out of scope for the
   reliability this data needs; the honest tradeoff documented in
   `wta_daily/plugins/matches/wta_official.py` is that this provider's
   output is always *real and verified*, even if - rarely, in a live
   event's opening days - it can lag behind the true latest result by a
   few days until the per-player endpoint catches up.

Both issues were fixed by adding one new official endpoint
(`WtaOfficialApiClient.get_tournament_matches`) rather than introducing a
third-party data source - `rankings_provider` is unaffected and still uses
`wta_official`, per the existing plugin design.

Also fixed: byes, walkovers/defaults, doubles, and not-yet-finished
fixtures are now explicitly excluded from "latest completed singles match"
(previously only implicit/accidental ordering luck kept a bye from ever
being picked).

### Combining a paid source with the free one (`best_of`)

The remaining limitation above - `wta_official` can lag real-world results
by over a week during a live event - motivated researching paid/commercial
tennis data APIs (see the provider comparison table above; short version:
the actually-official, exclusive WTA data partner is Stats Perform, and
it's enterprise-sales-only with no public pricing, so every self-serve
option is an independent, unlicensed-by-the-WTA aggregator).

[`livetennisapi.com`](https://livetennisapi.com) was selected to try: a
small, self-serve, transparently-priced aggregator ($9.99-$99.99/mo tiers)
whose completed-match records carry a genuine per-match `scheduled_time`
and an explicit `event_status` for retirements/walkovers/cancellations - no
tournament-date ambiguity to begin with. `wta_daily/plugins/matches/live_tennis_api.py`
implements the same `MatchProvider` interface against it. Player identity
isn't shared between the two APIs, so each player is resolved by name via
`GET /players?search=`, filtering out doubles teams and unranked namesake
noise entries (see `_pick_best_player_match`).

**Verified live against the real August 2026 Top 10, this paid source is
not reliable alone either**: 9 of 10 players' results exactly matched
`wta_official`'s independently-verified dates, but one player's record in
this vendor's system simply stopped four months earlier than the others' -
missing a Wimbledon final and a Toronto result, with no error or warning
to signal the gap. Vendor "real-time"/"accurate" marketing claims in this
space should not be taken as an SLA (see the commercial-options research
in the table above for the same caveat about several other vendors).

Rather than swap one imperfect source for another, `wta_daily/plugins/matches/best_of.py`
implements a `MatchProvider` that queries every configured source for a
player, isolates failures per source (one source erroring - or hitting its
free-tier rate limit, as happened live during testing - never blocks
another from being tried), and keeps whichever successful result has the
most recently *confirmed* `match_date`. This is the config example's
default (`match_provider.provider: best_of`, combining `wta_official` +
`live_tennis_api`) precisely because both underlying providers now recover
a genuine, verified per-match date - so "which result is actually more
recent" is an objective comparison, not a guess. Covered by
[`tests/test_best_of_match_provider.py`](tests/test_best_of_match_provider.py)
and [`tests/test_live_tennis_api_match_provider.py`](tests/test_live_tennis_api_match_provider.py)
(including a regression test for the exact stale-namesake-record case
above). `live_tennis_api`'s API key is resolved from the `LIVETENNISAPI_KEY`
environment variable (`api_key_env` in config) - never hardcoded; see
`.env.example`. To skip the paid source entirely, set
`match_provider: {provider: wta_official}` in `config.yaml`.

### A second paid source evaluated (`api_tennis`) - implemented, not enabled by default

[`api-tennis.com`](https://api-tennis.com) was tried as a third source
(`wta_daily/plugins/matches/api_tennis.py`), using a temporary trial key,
specifically to compare against the two sources above. Its shape is
different from `livetennisapi.com` - one endpoint with a `method=` query
parameter and the key passed as `APIkey=` rather than an `Authorization`
header - and player resolution is a direct name lookup against its
`get_standings` response (which conveniently returns every ranked player's
exact name *and* internal id in one call) rather than a fuzzy search.

**Live comparison against the same current WTA Top 10:**

- **Rankings matched `api.wtatennis.com` exactly** - same order, same point
  totals, for all 10 players.
- **Match coverage was better than `live_tennis_api`** for the one player
  who had a real multi-month gap there: `api_tennis` had her complete
  history through the correct Wimbledon final date.
- **A real, minor date-accuracy issue**: 4 of the 10 players' latest
  results came back exactly one calendar day *later* than the same
  matches' dates independently confirmed by both other sources (a
  plausible timezone-rollover artifact in how this vendor buckets match
  dates - opponent, score, and round were all still correct). This wasn't
  found in `wta_official`/`live_tennis_api`'s agreement with each other.
- One more vendor-specific quirk worth knowing: this API encodes some
  tiebreak set scores unconventionally (e.g. a 7-6(3) set can appear as
  `score_first: "6.3"`); rather than guess at reverse-engineering it, this
  provider passes those strings through as-is.

**Why it's implemented but not in `best_of`'s default source list**:
`best_of` picks whichever source's date is most recent, so adding a source
with an occasional one-day-*late* drift means it can outrank a same-event,
more-accurate date from another source - exactly the 4-player pattern
above would reproduce if all three sources were combined. This is a
real, measured tradeoff, not a hypothetical one: enable it deliberately
(see `config.example.yaml`) if you want the extra redundancy and are fine
with that risk, e.g. as a `live_tennis_api` replacement if you don't have
a key for that service. Covered by
[`tests/test_api_tennis_match_provider.py`](tests/test_api_tennis_match_provider.py).
Its API key is resolved from `APITENNIS_KEY` (`api_key_env` in config) -
never hardcoded. (Note: `get_matches_for_date`, described next, only
accepts a source's result when its date matches the target day exactly, so
this drift now mostly makes `api_tennis` silently miss a match rather than
report a wrong one - safer than it would have been before, but still not
a reason to default to it.)

### From "her latest match" to "did she play yesterday" (day-first matching)

A second production run exposed a deeper problem than the tournament-date
bug above: even with a correct date, `wta_official`'s per-player history
endpoint (`GET /players/{id}/matches`) can lag the *current* tournament
week by several days. Confirmed live: three Top 10 players had already won
a second-round match at that week's tournament while this endpoint still
showed nothing past the *previous* week's event for any of them - so asking
"what's her latest match" answered with a real, correctly-dated, but
substantively **stale** result once the report is meant to be about a
specific day (e.g. "yesterday").

Investigated and ruled out as a fix for this specific problem: the official
[`developers.wtatennis.com`](https://developers.wtatennis.com) portal
(JS app behind a login wall requiring Microsoft SSO or a pre-issued
"Subscription ID" - no public signup found, not pursued further per "don't
bypass access controls"). What *did* solve it: the WTA's own live-scores
page turns out to be built on the exact same `api.wtatennis.com` backend
already in use here - confirmed directly from the site's own frontend
config (`"api": "https://api.wtatennis.com"`) - just read through a
different, near-real-time endpoint (the tournament-level one, already used
above for date recovery) instead of the slow per-player one.

**The fix: flip the query direction.** Instead of *"for each Top N player,
what's her latest match"* (player-first), the pipeline now asks *"which
matches finished on this exact date, and which of them involve a Top N
player"* (day-first):

1. `MatchProvider.get_matches_for_date(players, target_date)` is the new
   primary interface method (see `wta_daily/plugins/base.py`) -
   `get_latest_match` still exists (some providers/tests still use it, and
   it has a real, different meaning - "whatever this provider's most recent
   *known* result is, regardless of date"), but the pipeline no longer calls
   it directly.
2. `WtaOfficialMatchProvider.get_matches_for_date` scans the tournament
   catalogue for events active on the target date (there's no working
   date filter on that endpoint, so this pages through the *last* ~25
   pages of the ~19,000-entry, roughly-chronological catalogue - the
   current season is always near the end, and this is a few seconds of
   work once per run, not per player), fetches each active tournament's
   full match list, and keeps only genuinely finished (`MatchState: "F"`)
   singles matches whose real per-fixture timestamp falls on that exact
   UTC calendar day. A player absent from the result gets `played: false`
   - **nothing ever falls back to an older match.**
3. `MatchProvider`'s default `get_matches_for_date` (used by `sample`,
   `live_tennis_api`, `api_tennis`, which don't have a day-indexed lookup
   of their own) falls back to `get_latest_match` per player, keeping the
   result only if its date exactly equals the target date - honest (never
   claims a wrong date), but can under-report a match that source's
   per-player history hasn't caught up on yet. Only `wta_official`'s
   override actually fixes the staleness; the others just avoid making it
   worse.
4. `BestOfMatchProvider.get_matches_for_date` tries every source in turn,
   removing a player from consideration as soon as any source confirms a
   match for them, and only raises if **every** source fails outright -
   a player confidently absent from a source that itself completed without
   error is reported as `played: false`, not as an error. This same
   per-source isolation now also covers **construction**, not just lookups:
   if a configured source can't even be built (e.g. a paid source's API key
   hasn't been set yet), that source is skipped with a logged warning
   instead of crashing the whole run, as long as at least one other
   configured source is usable - `ConfigurationError` is raised only if
   every configured source fails to construct. This is what lets the
   default config ship with both `wta_official` and `live_tennis_api`
   listed, even though only the free one is guaranteed to work out of the
   box.
5. `report.json` gained a top-level `match_target_date` field (the actual
   UTC date being asked about - `report_date` minus
   `match_target_date_offset_days`, default 1 = yesterday) so every
   consumer (narration, graphics, and anyone reading the file later) knows
   exactly what date `played`/`match` answer for.

**Verified against a real historical date (August 14, 2026) with zero
discrepancies against three independent sources** (BBC Sport, and two
tennis-news outlets, cross-checked against the WTA's own scores page): on
that date, none of the (then-)current Top 10 had played yet (seeded players
get a first-round bye in a 96-draw event and start in Round 2) - the
day-first lookup correctly reported `played: false` for all ten, and
separately, correctly found three players' real wins the very next day,
matching those same sources exactly (opponent, score, round, and date).

One remaining, explicitly accepted tradeoff: a match found only through the
day-first tournament scan (i.e. one the per-player endpoint hasn't caught
up on yet) can't be cross-referenced against that endpoint's nicer
`R16`/`Quarterfinal`-style round names, since there's nothing to
cross-reference. Those matches get a plainer `"Main Draw Round 2"`-style
label instead, built directly from the tournament feed's own fields -
correct, just less polished until the per-player endpoint does catch up.
Opponent, score, date, and win/loss are unaffected.

**Timezone handling**: `MatchTimeStamp` is UTC (`+00:00`/`Z`) for finished
matches, but the *same field* on not-yet-played fixtures in the same
response can be in tournament **local** time with an explicit offset (e.g.
`-04:00` for Cincinnati) - a genuine inconsistency in this API, and a
plausible explanation for `api_tennis`'s date drift above. `_parse_timestamp`
(`wta_daily/plugins/matches/wta_official.py`) always normalizes to UTC
before taking the calendar date, and "yesterday" is defined project-wide as
**UTC calendar yesterday relative to when the job runs** - deterministic
and reproducible regardless of which tournament's timezone a match was
actually played in.

## Understanding & optimizing API usage

An August 2026 audit (prompted by wanting to add featured-player lookups
without multiplying request volume) walked every external HTTP call one
normal daily run makes, end to end, and applied the safe optimizations that
came out of it - summarized here.

### What a normal run actually calls (verified live, `wta_official` alone)

```
1x  GET /tennis/players/ranked                       ("WTA rankings")
1x  GET /tennis/tournaments?page=0                   ("WTA tournament discovery" - learns total entry count)
25x GET /tennis/tournaments?page=N                    ("WTA tournament discovery" - scans the last ~2,500-entry window for active tournaments; see catalogue_scan_pages)
1x  GET /tennis/tournaments/{groupId}/{year}/matches  ("WTA match results" - one call per *active* tournament this week, not per player)
------------------------------------------------------------------------
28 total (verified live, August 2026, real Top 10, one active tournament that week)
```

**Rankings: already minimal, now reusable.** `get_top_n(n)` has always been
exactly one HTTP call (`page_size=n`) regardless of `n` - fetching a Top 25
pool instead of a Top 10 one does not add a request, it just asks the same
single call for a few more rows. The pipeline now does exactly that
(`rankings_pool_size` in config, default 25): it fetches the pool once,
slices the first `top_n` for the actual report, and keeps the rest on
`DailyPipeline.last_rankings_pool` and in the `players.json` metadata cache
for a future featured-player lookup to reuse - so that feature, whenever
it's built, should never need a dedicated rankings request of its own.
Movement-comparison history (`rankings-history.json`) deliberately stays
scoped to exactly `top_n`, never the wider pool - see
`RankingsSnapshotStore.save_snapshot`'s docstring for why widening it would
silently break what "NEW" means.

**Match data: already batched correctly, one avoidable duplicate removed.**
`WtaOfficialMatchProvider.get_matches_for_date` was already built around the
preferred "fetch once, normalize, match locally against every tracked
player" shape, not "one API call per player" - `_get_tournament_matches`
has always cached each tournament's match list per run, so N players
sharing one active tournament costs exactly one HTTP call, not N. The one
real duplication risk (page 0 fetched once for the total entry count, and
then again if it also happened to fall inside the scan window) is now
prevented unconditionally: `WtaOfficialApiClient.list_tournaments_page`
caches every page it fetches per `(page, page_size)` for the lifetime of one
run, so asking for the same page twice - by this code path or any future
one - never issues a second real request. The `catalogue_scan_pages` scan
itself (~25 pages) is **not** reduced, since there's no safe way to know in
advance how far back the current season's entries start in that endpoint's
roughly-chronological catalogue, and guessing wrong would silently miss an
active tournament - exactly the kind of "faster but less reliable" tradeoff
this audit was told not to make. It's fully configurable
(`match_provider.sources[].catalogue_scan_pages`) for anyone who wants to
tune it against their own observed data using the instrumentation below.

**Fallback providers: this is where the real waste was.** Before this
audit, `BestOfMatchProvider.get_matches_for_date` treated "this source
didn't return a match for player X" as "still need to ask the next source
about her" - which meant that on a normal day, when the large majority of
the Top 10 simply didn't play, *every one of them* triggered a fallback
query to `live_tennis_api` (and any other configured paid source), every
single day, purely because "no match" looked identical to "couldn't check."
Fixed by introducing `MatchLookupResult` (`wta_daily/models.py`): a source
now reports `unresolved_player_ids` distinctly from a confirmed absence, so
`BestOfMatchProvider` only carries a player forward to the next source when
her status is genuinely still in doubt (a fetch failure), never merely
because she didn't play. Verified live: with `LIVETENNISAPI_KEY` set to a
placeholder (so the source constructs successfully and *could* be called),
`wta_official` alone confidently accounted for the entire Top 10 on a
representative day, and `LiveTennisAPI` recorded **zero** requests for that
run - the paid source is only ever actually queried when `wta_official`
itself couldn't determine a specific player's status (see
`tests/test_best_of_match_provider.py`'s
`test_get_matches_for_date_does_not_call_a_later_source_for_a_confirmed_negative`
and `..._only_queries_genuinely_unresolved_players_on_later_sources`). This
is a strict improvement in both directions at once: fewer (often paid, rate
limited) requests on a normal day, *and* better accuracy than before on the
one day it matters, because a source whose fetch genuinely failed for one
player is now escalated correctly instead of that player being silently
absorbed into "no match" the same as everyone who simply didn't play.

### Understanding API usage in your own runs

Every outbound request to `api.wtatennis.com`, `livetennisapi.com`, and
`api-tennis.com` is tallied per run (never per URL/params/headers, so this
can't leak a key) and logged as a summary right before "Finished
successfully":

```
External API requests:
  WTA match results: 1
  WTA rankings: 1
  WTA tournament discovery: 26
  Total: 28
```

A category that was never called (e.g. a disabled or successfully-avoided
fallback source) is simply omitted rather than shown as zero, so this
summary always reflects exactly what happened. Run with `--verbose` to also
see each individual request logged as it happens
(`wta_daily.api_usage: External API request recorded: ...`), in order - see
`wta_daily/api_usage.py`.

### What was deliberately left alone

- **`catalogue_scan_pages` (~25 pages) is not reduced** - see above; this is
  the single largest remaining cost (26 of 28 requests in the measurement
  above) and a legitimate target for a *future*, carefully-verified
  optimization (e.g. persisting a "last known good starting page" hint
  across runs), but doing that safely needs its own dedicated
  live-verification pass, not a guess bundled into this audit.
- **No cross-run cache for rankings or match results** - both are
  inherently time-sensitive; caching them across days would risk exactly
  the staleness this project was built to fix. Only genuinely stable data
  (player name/country - `players.json`) is cached long-term.
- **No persistent player-id cache for the paid sources** (`live_tennis_api`
  resolves a name to its own numeric id via a search call, `api_tennis` via
  one cached-per-run standings call) - left as a per-run cache only,
  since after the fallback fix above these sources are called rarely enough
  that persisting their id mappings across days is unlikely to be worth the
  added complexity. Revisit if instrumentation on a real deployment shows
  otherwise.

## Featured player (recurring editorial segment)

A small, opt-in, recurring spotlight on one specific player - shipped
configured for Emma Navarro (WTA player id `325410`) with a running
"America's favorite" joke, disabled by default. It exists specifically so
the official Top N coverage never has to compromise on being factual: every
number in this segment comes from the exact same
`RankingsProvider`/`MatchProvider` architecture as the Top N (see
["Architecture & extending it"](#architecture--extending-it)) - only the
*narration wording* built from those facts is allowed a sense of humor, and
only in this one segment.

### Enabling it

```yaml
featured_player:
  enabled: true
  player_id: "325410"   # Emma Navarro's real api.wtatennis.com player id
  name: Emma Navarro
  tagline: america_favorite
```

`tagline` selects which narration personality/phrase pool flavors the
commentary - currently only `america_favorite`
(`wta_daily/scripts_gen/featured_player_phrases.py`) ships, but nothing
about the mechanism is Emma-specific by name: pointing a different
`player_id`/`name` at the same tagline works today, and a future player
with their own running joke would just need a sibling phrase module and a
new tagline value - no pipeline changes.

### How her data is retrieved (no bespoke lookups)

- **Ranking**: `DailyPipeline` already fetches a rankings *pool* larger than
  `top_n` in one request each run (see "Understanding & optimizing API
  usage" above). The featured player's ranking is looked up in that same
  pool first - free, since it's the identical response already in memory.
  Only if she isn't in it (e.g. she's ranked outside the configured
  `rankings_pool_size`) does the pipeline fall back to **one** additional
  `RankingsProvider.get_top_n(n)` call for a larger page - the same
  provider interface used everywhere else, never a dedicated "look up one
  player" endpoint.
- **Match**: she's added to the exact same batched
  `MatchProvider.get_matches_for_date(...)` call already made for the Top
  N (only if she isn't already one of them) - for `wta_official`'s
  day-first tournament scan, this costs **zero** extra HTTP requests,
  since that scan already reads every active tournament's full match list
  regardless of which specific players are being checked against it.
- **Movement**: `RankingsSnapshotStore` records her rank separately from
  the tracked Top N group (a `featured_players` entry alongside each day's
  snapshot) purely so `get_previous_player_rank` can answer "what was her
  rank last time" the same way it would for anyone in the Top N - this
  never affects what counts as "NEW" for the official group.

### Failure isolation

Every step above is wrapped so a failure (rank lookup, match lookup, or an
unexpected error while assembling the section) can never abort or affect
the Top N report - it's logged, recorded in `report.json`'s `errors` list
for visibility, and the featured-player section simply omits whatever
couldn't be determined (`rank`/`match` stay `null`, no default/guessed
values). See `DailyPipeline._safe_resolve_featured_player_ranking` and
`_safe_build_featured_player_report`.

### Report output

Lives in its own `featured_player` object in `report.json` - never merged
into the official `players` list, even on the (rare, but handled) day she's
actually ranked inside the Top N, so a consumer can always tell "official
Top N" apart from "editorial spotlight":

```json
"featured_player": {
  "name": "Emma Navarro",
  "player_id": "325410",
  "tagline": "america_favorite",
  "rank": 28,
  "points": 1669,
  "movement": "same",
  "previous_rank": 28,
  "played": true,
  "won": true,
  "opponent": "Anhelina Kalinina",
  "score": "3-6,6-4,6-2",
  "tournament": "Cincinnati",
  "round": "Main Draw Round 2",
  "match_date": "2026-08-15"
}
```

### Narration tone and variation

`wta_daily/scripts_gen/featured_player.py` builds a short (1-3 sentence)
paragraph inserted after every Top N player and before the final sign-off.
Several independent template axes (intro, "favorite" label, movement
flavor, Top N framing, match result, and an occasional - not daily -
"#1 in our hearts" aside, gated at a fixed probability) are drawn from the
same per-run seeded `random.Random` the rest of the script already uses,
so wording varies day to day without ever repeating a canned paragraph, and
a report with the feature disabled produces byte-identical output to
before this feature existed. Framing adapts automatically to her real rank:
"pursuit" language while she's outside the Top N, "arrived" language the
day she's genuinely inside it (the "trying to break in" framing is retired
the moment it stops being true), and a distinct, joke-free acknowledgment
if she ever reaches world No. 1 - see
`tests/test_featured_player_narration.py` for the full set of tone rules
enforced by tests (never a mathematically specific pursuit claim, never a
fabricated match result, never "new"/"debut" language on a first-ever run,
substantial variation across at least a few dozen days).

Graphics were deliberately left untouched for this feature (the official
leaderboard stays the official leaderboard) - the priority here was data
correctness and narration, per the feature's own scope.

## Narration pronunciation (ElevenLabs)

Two problems showed up once ElevenLabs narration (`voice.enabled: true`)
was actually in use, both fixed without touching `script.txt` or
`report.json` - the fix only changes what's sent to ElevenLabs for
synthesis, right before the API call.

### 1. What caused the problems

* **Player names**: `ElevenLabsVoiceSynthesizer.synthesize` sent
  `script.txt` to ElevenLabs completely as-is. With no pronunciation
  guidance attached, ElevenLabs falls back to generic English
  letter-to-sound rules, which mishandle several WTA surnames whose
  spelling doesn't map onto English pronunciation conventions -
  `"Swiatek"` (real pronunciation roughly "shvee-ON-tek") is the most
  notorious example, but `"Muchova"`, `"Krejcikova"`, `"Chwalinska"`,
  `"Jovic"`, and `"Cirstea"` all come out noticeably wrong by default too.
* **Scores**: a score string like `"3-6,6-4,6-2"` is unambiguous written
  down, but a general-purpose TTS engine has no tennis-specific grammar -
  a bare `N-M` reads naturally as a numeric *range* ("three to six"), and
  stacking several with commas compounds the confusion.

### 2. Options considered

| Option | Verdict |
| --- | --- |
| ElevenLabs **phoneme rules** (IPA/CMU) in a pronunciation dictionary | Most precise in principle, but ElevenLabs' own docs are explicit that phoneme tags only take effect on the `eleven_flash_v2`/`eleven_v3` models - every other model, **including this project's configured default `eleven_multilingual_v2`** (see `VoiceConfig.model_id`), silently ignores them. Ruled out for the names dictionary as currently configured; noted below as an option if the model ever changes. |
| ElevenLabs **alias rules** in a pronunciation dictionary | A plain-text respelling substituted at synthesis time, supported by **every** model. Never changes the underlying text - report.json/script.txt still show the correctly-spelled name. **Chosen for player names.** |
| Full **SSML** (e.g. inline `<phoneme>` tags in the request text) | ElevenLabs' TTS API does not support general inline SSML phoneme/pronunciation tags in the request text itself - pronunciation dictionaries are the supported mechanism for this, not markup embedded in `text`. Ruled out - not available for the model in use. |
| ElevenLabs' built-in **text normalization** (`apply_text_normalization`) | A coarse, generic normalizer (dates, currency, etc.), not tennis-aware - it has no notion of "this hyphen separates two game counts," so it wouldn't reliably turn `"3-6"` into "three six" rather than "three to six" or "three dash six." Ruled out for scores. |
| Hard-coded **literal score lookup table** | Scores are an open-ended pattern (any `N-M`, any number of sets, optional tiebreak sub-scores) - a literal table would be both incomplete and unmaintainable. Ruled out in favor of a general rule. |
| Custom **rule-based text normalization**, applied only to the TTS input | General (covers any score, not a fixed list), maintainable, and has no equivalent "native" ElevenLabs mechanism to defer to instead (dictionaries only match finite literal strings, not open-ended patterns). **Chosen for scores.** |

### 3. Solution chosen, and why

* **Player names -> ElevenLabs pronunciation dictionary (alias rules)**,
  managed by `wta_daily/voice/pronunciation_dictionary.py`. A curated,
  maintainable `PLAYER_NAME_ALIASES` dict (surname -> phonetic respelling)
  is uploaded via `POST /v1/pronunciation-dictionaries/add-from-rules`
  and attached to every synthesis request via
  `pronunciation_dictionary_locators`. This is the ElevenLabs-native
  mechanism the task asked to prefer over a fragile workaround - it
  changes only the *audio*, never the text.
* **Scores -> a small regex-based normalizer**,
  `wta_daily/voice/narration_text.py`. Detects any run of `N-M` or
  `N-M(T)` tokens (comma/space separated - covering every format our
  match providers actually produce, e.g. `"6-4 6-2"` and `"6-3,6-2"`) and
  spells each set out in words with a natural pause between sets,
  regardless of what the specific numbers are. Applied only to the text
  handed to the ElevenLabs API, immediately before that call.

### 4. Before / after

```text
BEFORE (as sent to ElevenLabs, before this fix):
  ...closing it out 6-3,6-2 at Cincinnati.

AFTER (as sent to ElevenLabs, after this fix):
  ...closing it out six three, six two at Cincinnati.
```

```text
BEFORE: 7-6(4) 4-6 6-3
AFTER:  seven six, four six, six three
```

`report.json`/`script.txt` are byte-for-byte unaffected in both cases -
verified live against a real generated script (see
`tests/test_narration_text.py` and `tests/test_elevenlabs_provider.py`):

```json
"score": "6-3,6-2"   // report.json - unchanged, exactly as before
```

### 5. Effect on ElevenLabs input

`ElevenLabsVoiceSynthesizer.synthesize` now, in order:

1. Reads `script.txt` (unchanged).
2. Runs it through `normalize_for_speech` (scores only, for now) to build
   a separate, speech-only `text` value - never written back to disk.
3. Resolves a pronunciation-dictionary locator via
   `get_or_create_locator`, which checks a small on-disk cache
   (`data/cache/elevenlabs_pronunciation_dictionary.json`, alongside the
   project's other provider-level caches - see "Folder structure") keyed
   by a hash of the current alias list, and only calls the ElevenLabs API
   to create/update the dictionary if that cache is missing or stale.
   **A normal day-to-day run makes zero extra API calls** - verified by
   running `synthesize()` twice in a row with the HTTP layer mocked: the
   `add-from-rules` call happens once, not on the second run (see
   `tests/test_pronunciation_dictionary.py`).
4. Sends one `POST /v1/text-to-speech/{voice_id}` request with the
   speech-only text and (if step 3 succeeded) a
   `pronunciation_dictionary_locators` entry - the same single request as
   before this change, just with better input.

Any failure in steps 2-3 degrades gracefully (logs a warning, proceeds
without the dictionary) rather than blocking narration - only a genuine
failure of the text-to-speech call itself (step 4) raises
`VoiceSynthesisError`, same as before this change.

### 6. Limitations / names that still need manual tuning

* `PLAYER_NAME_ALIASES` is a curated, by-ear list (currently: Świątek,
  Sabalenka, Muchova, Krejcikova, Bouzkova, Chwalinska, Jovic, Cirstea) -
  not exhaustive. Adding a newly-mispronounced name is a one-line edit to
  that dict; no other code changes needed, and the dictionary is
  recreated automatically the next time that list's content changes.
* Alias respellings are an approximation (English graphemes standing in
  for non-English sounds), not exact phonetics - if this project ever
  switches `voice.model_id` to `eleven_flash_v2`/`eleven_v3`, precise IPA
  phoneme rules become available and could replace some aliases for
  closer accuracy (the dictionary-management code already supports adding
  phoneme-type rules; only `PLAYER_NAME_ALIASES`'s rule *type* per entry
  would need to change).
* The tiebreak point count in a score like `"7-6(4)"` is intentionally
  **dropped** for speech (spoken as "seven six", not "seven six four") -
  reading it as a third bare number right after the set score would be
  more confusing than informative, and the set score that actually
  matters for narration is unaffected. The written score keeps the full
  `"7-6(4)"` detail everywhere else.
* Set `voice.pronunciation_dictionary_enabled: false` to disable
  attaching the dictionary (e.g. while debugging) without disabling voice
  synthesis entirely.

### 7. Tests

`tests/test_narration_text.py` (score normalization, including the exact
reported example, tiebreak notation, double-digit super-tiebreaks, and a
regression guard proving a hyphenated date is never misread as/clipped
into a score), `tests/test_pronunciation_dictionary.py` (create-once-and-
cache behavior, cache invalidation when the alias list changes, and
graceful failure), and `tests/test_elevenlabs_provider.py` (the full
synthesize() flow: speech text is normalized, script.txt is never
modified, the locator is attached when available and omitted when not,
and the feature can be disabled via config) - all using mocked HTTP, so
`pytest` never calls the real ElevenLabs API.

## Player imagery: legal approach

The brief is explicit: don't download copyrighted player headshots. This
project doesn't download *any* player images. Instead, country flags on the
leaderboard and player cards are rendered from the **Unicode emoji
standard** (`wta_daily/countries.py` + `wta_daily/graphics/flags.py`), using
whatever color emoji font is installed on the machine (e.g. Noto Color
Emoji). National flags are not copyrightable and Unicode code points are a
text standard, not artwork requiring a license - so there is nothing to clear
or attribute.

For a player's *photo* (should a future phase want one - e.g. for a
thumbnail), the recommended long-term approaches, in order of preference,
are:

1. **AI-generated editorial illustration** - a stylized, clearly-illustrated
   likeness (not a photorealistic copy of a copyrighted photograph) generated
   per player. Lowest legal risk, fully controllable style, no attribution
   required. This is the recommended default if a "photo-like" element is
   ever added.
2. **Public domain or Creative Commons images with proper attribution** -
   e.g. Wikimedia Commons frequently hosts CC-BY/CC-BY-SA photos from
   photographers who explicitly release usage rights; if used, the specific
   license and photographer credit must be stored alongside the asset and
   shown on screen/description per that license's terms.
3. **Never**: scraping or hot-linking press photos, official WTA/tournament
   photography, or sponsor/broadcast imagery - these are copyrighted and not
   licensed for redistribution in a third-party video.

Phase 1 doesn't need any of this - the graphics are flags + typography +
data, which is already enough for a clean broadcast look.

## Quick start

Requires Python 3.11+ (see [Raspberry Pi deployment](#raspberry-pi-deployment)
for why - short version: Python 3.9 is EOL and current Pillow already
requires 3.10+). `ffmpeg` is only needed if you enable video assembly.
For development on Windows via Cursor, any 3.11+ interpreter works fine;
this is just for local dev - see the Raspberry Pi section for the
production deployment steps (`deploy/bootstrap_pi.sh` etc.).

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp config/config.example.yaml config/config.yaml
cp .env.example .env             # only needed once you enable voice/OpenAI

# Run today's job (writes to output/<today>/):
python -m wta_daily.cli --config config/config.yaml

# Or pin a specific date (useful for testing/backfilling):
python -m wta_daily.cli --config config/config.yaml --date 2026-08-09 --verbose
```

A successful run produces, for the target date, everything Phase 1 promises:

```text
output/2026-08-09/
    report.json
    script.txt
    leaderboard.png
    player_cards/
        01.png
        02.png
        ...
```

To try it fully offline first (no network calls at all), point the config at
the bundled `sample` providers:

```yaml
rankings_provider:
  provider: sample
match_provider:
  provider: sample
```

### Running the test suite

```bash
pip install -e ".[dev]"
pytest
ruff check wta_daily tests
mypy wta_daily
```

## Configuration

Everything tunable lives in one YAML file - see the fully-commented
[`config/config.example.yaml`](config/config.example.yaml). Copy it to
`config/config.yaml` (git-ignored) before running. Highlights:

- `top_n` - how many players to track (10 by default; flip to 25 any time).
- `match_target_date_offset_days` - which day counts as "the day we're
  reporting match results for" (1 = yesterday, UTC; see "From 'her latest
  match' to 'did she play yesterday'" above).
- `rankings_provider` / `match_provider` - `{provider: <name>, ...options}`;
  `<name>` is looked up in the plugin registry (see below).
- `featured_player` - the recurring "America's favorite" Emma Navarro
  segment; `enabled: false` by default. See ["Featured player"](#featured-player-recurring-editorial-segment) above.
- `script.generator` - `template` (default, offline, free) or `openai`
  (requires `OPENAI_API_KEY`).
- `graphics.theme` - all colors, plus optional custom font paths.
- `voice` / `video` / `git` - Phase 2 features, all `enabled: false` by
  default.

**Secrets are never stored in the config file.** Each secret-consuming
setting is a `..._env` field naming an *environment variable* (see
[`.env.example`](.env.example)); the actual key is resolved from the process
environment (a local `.env` file via `python-dotenv`, your shell, or your
CI/scheduler's secret store) at run time. `wta_daily/config.py` raises a
clear `ConfigurationError` if a feature is enabled but its key is missing -
it never silently sends an empty key or hardcodes a placeholder.

## Folder structure

```text
wta-daily/
    wta_daily/              # the installable Python package (see below)
    data/
        rankings-history.json   # append-only daily snapshots, for movement comparison
        players.json             # small player_id -> {name, country_code} cache
        sample/                   # offline fixtures used by tests/demos
        cache/                    # scratch space for provider-level caching
    output/
        2026-08-09/              # one self-contained folder per day
            report.json
            script.txt
            narration.mp3         # Phase 2, only if voice.enabled
            leaderboard.png
            player_cards/
            video.mp4              # Phase 2, only if video.enabled
    config/
        config.example.yaml
    templates/               # reserved for future templated assets (intros, thumbnails)
    assets/                  # custom fonts / background music you supply
    tests/
    logs/
        wta-daily-2026-08-09.log
```

## Architecture & extending it

```text
CLI (wta_daily/cli.py)
  -> load_config()                     wta_daily/config.py
  -> DailyPipeline.run()                wta_daily/pipeline.py
       1. RankingsProvider.get_top_n()          <- plugin: rankings_registry
       2. compute_movement() vs snapshot store  wta_daily/movement.py (UNKNOWN if no prior snapshot exists at all)
       3. MatchProvider.get_matches_for_date()   <- plugin: matches_registry  (day-first batch call; a player absent from the result is played: false, never an older match)
       4. RankingsSnapshotStore.save_snapshot() wta_daily/persistence/snapshot_store.py
       5. DailyOutputStore.write_report()       wta_daily/persistence/report_store.py
       6. ScriptGenerator.generate()            <- plugin: script_registry
       7. GraphicsRenderer.render_*()           <- plugin: graphics_registry
       8. [optional] VoiceSynthesizer.synthesize()  <- plugin: voice_registry
       9. [optional] VideoAssembler.assemble()      <- plugin: video_registry
      10. [optional] git_automation.commit_and_push()
```

Every numbered step other than movement/persistence is a **plugin**: a small
abstract base class in `wta_daily/plugins/base.py`
(`RankingsProvider`, `MatchProvider`, `ScriptGenerator`, `GraphicsRenderer`,
`VoiceSynthesizer`, `VideoAssembler`). Concrete implementations register
themselves with a decorator against one of the registries in
`wta_daily/plugins/registry.py`:

```python
@rankings_registry.register("my_new_source")
class MyNewRankingsProvider(RankingsProvider):
    def get_top_n(self, n: int) -> list[PlayerRanking]:
        ...
```

and get selected purely from `config.yaml`:

```yaml
rankings_provider:
  provider: my_new_source
  some_option: 42
```

`DailyPipeline` only ever talks to the abstract interfaces - it has no
knowledge of `api.wtatennis.com`, ElevenLabs, ffmpeg, or anything else
concrete. That's what makes each of these additions a "write one file, wire
it into `load_builtin_plugins()`" change instead of a pipeline rewrite:

- **ATP version**: add `wta_daily/plugins/rankings/atp_official.py` and
  `wta_daily/plugins/matches/atp_official.py` implementing the same two
  interfaces against whatever ATP data source you choose, register them, set
  `tour: atp` and the new provider names in config. `rankings-history.json`
  already stores a `tour` field per snapshot so ATP and WTA history can
  coexist.
- **Top 25 instead of Top 10**: change `top_n: 25` in config. Nothing else.
- **Combine several data sources for one concern**: plugins can compose
  other plugins purely through the registry - `wta_daily/plugins/matches/best_of.py`
  is a real example: it's itself a `MatchProvider` that constructs and
  queries several other registered `MatchProvider`s (`wta_official` +
  `live_tennis_api` by default) and picks the best result, with no special
  casing anywhere else in the pipeline. The same pattern works for any
  plugin category - e.g. a `best_of` `RankingsProvider` that cross-checks
  two ranking sources would look identical in shape.
- **Daily single-player tracker** (e.g. "Emma Navarro tracker"): a thin
  wrapper pipeline (or a config with `top_n: 1` plus a custom rankings
  provider that filters to one player) reusing every other module unchanged.
- **Spanish/French narration**: add
  `wta_daily/scripts_gen/template_generator_es.py` with translated phrase
  pools (mirroring `wta_daily/scripts_gen/phrases.py`), register it as
  `template_es`, select it via `script.generator: template_es`.
- **Tournament previews, head-to-head stats, player bios, injury reports,
  weather, historical ranking charts, YouTube description generation,
  thumbnail generation**: each is a new, independent module that reads from
  `report.json`/`players.json`/`rankings-history.json` and writes its own
  output file into the day's folder - none of them need to touch
  `DailyPipeline`, `models.py`, or any existing plugin.

## Error handling & logging

- **One player's failure never aborts the run.** `MatchProvider`'s default
  `get_matches_for_date` (used by any source without a native day-indexed
  lookup) isolates each player's `get_latest_match` call in its own
  try/except; a player whose lookup fails simply doesn't appear in that
  source's result (same as if she hadn't played - see "From 'her latest
  match' to 'did she play yesterday'" above for why that's the honest
  outcome for a per-item failure with no separate "unknown" channel to put
  it in). `BestOfMatchProvider` isolates failures per *source* the same way.
  Covered by `tests/test_match_provider_base.py` and
  `tests/test_pipeline_integration.py::test_pipeline_continues_when_one_players_match_fails`.
- **A total match-lookup failure (every source down, or the sole configured
  one failing outright) is different and *is* flagged**: every player is
  reported as `played: false` *with* a `match_error` message attached, so
  `report.json` can distinguish "we confirmed she didn't play" from "we
  couldn't check." Covered by
  `tests/test_pipeline_integration.py::test_pipeline_marks_every_player_with_match_error_on_total_batch_failure`.
- **Rankings failing is fatal for that run** (there is nothing to report
  without them) - `DataProviderError` propagates out of `DailyPipeline.run()`
  and the CLI logs it clearly and exits non-zero, rather than writing a
  half-empty report.
- **Every run writes a dated log file** to `logs/wta-daily-<date>.log` (see
  `wta_daily/logging_setup.py`) in addition to console output, so a failure
  discovered the next morning can be traced back to a specific run.
- HTTP calls (`wta_daily/http_client.py`) retry transient failures with
  exponential backoff before giving up, configurable via `network:` in
  `config.yaml`.
- **Match-date enrichment failing never drops the whole match.** If the
  tournament-level lookup used to recover a real match date (see "Match-data
  reliability" above) can't confirm one - network hiccup, fixture not found,
  endpoint shape change - `WtaOfficialMatchProvider` logs it and returns the
  match anyway with `match_date: null`; it never raises, and it never
  substitutes a tournament date as a "good enough" guess.

## Scheduling

The CLI (`python -m wta_daily.cli --config config/config.yaml`) is a single,
idempotent-per-date command, so it works the same way under any scheduler:

- **cron**: `0 6 * * * cd /path/to/wta-daily && .venv/bin/python -m wta_daily.cli --config config/config.yaml >> logs/cron.log 2>&1`
  (a ready-to-use, `flock`-guarded version of this line lives in
  [`deploy/cron/wta-daily.cron`](deploy/cron/wta-daily.cron)).
- **systemd timer** (recommended on Linux/Raspberry Pi - see below) - unit
  files in [`deploy/systemd/`](deploy/systemd/).
- **Windows Task Scheduler**: point an action at
  `...\.venv\Scripts\python.exe -m wta_daily.cli --config config\config.yaml`,
  trigger daily.
- **GitHub Actions**: a scheduled workflow (`on: schedule`) that checks out
  the repo, installs `requirements.txt`, runs the CLI, and (if desired)
  commits/pushes the new `output/<date>/` folder - see `wta_daily/git_automation.py`
  for the same commit logic the CLI can run locally via `git.auto_commit`.

Changing the schedule never requires touching source code - only the
scheduler's own trigger configuration.

## Raspberry Pi deployment

This project is designed to run unattended on a **Raspberry Pi 4 Model B**
that also runs **Pi-hole** - so every choice below is made to (a) never
disrupt Pi-hole, (b) avoid unnecessary system-wide changes, and (c) work
headlessly over SSH.

### Target environment

The Pi 4's SoC (Cortex-A72) is 64-bit-capable, and the recommended target is
a clean install of the current **Raspberry Pi OS (Debian 13 "Trixie"), Lite,
64-bit**, which ships **Python 3.13** as the system interpreter - fully
supported and security-patched, with broad `piwheels`/PyPI ARM64 wheel
coverage (no more compiling C extensions from source than necessary). If you
need the most conservative/battle-tested option instead, **Bookworm (Debian
12), Lite, 64-bit** (Python 3.11, supported for a couple more years) is a
perfectly good fallback - either satisfies `requires-python = ">=3.11"`.

We deliberately do **not** recommend an in-place `apt dist-upgrade` across
major Raspberry Pi OS versions (e.g. Bullseye -> Bookworm/Trixie) - Raspberry
Pi's own guidance is that this is unsupported and can leave a Pi unable to
boot. A clean reflash (Raspberry Pi Imager, new SD card) plus migrating your
Pi-hole configuration is the safe, officially-supported path:

1. **Back up Pi-hole**: Admin UI -> Settings -> Teleporter (or `pihole -a -t`
   on the CLI). This exports your blocklists, allow/deny lists, and DHCP
   settings as one archive.
2. **Flash a new SD card** with Raspberry Pi Imager - Raspberry Pi OS Lite,
   64-bit, Trixie (or Bookworm). Keep the old card as a fallback until
   you're confident in the new one.
3. Boot the new card, run the standard Pi-hole installer, then **restore**
   the Teleporter backup from step 1.
4. Deploy this project (below) - the system Python is now current, so none
   of the "isolated interpreter" workarounds an older OS would need are
   necessary.

If you're staying on an older/32-bit OS for now (e.g. Bullseye, Python
3.9.2, `armv7l`), see the note at the end of this section.

### Deploying the project

Everything below only ever touches your own home directory and your own
user-level systemd/cron entries - never `apt`, never a system Python, never
anything Pi-hole depends on.

```bash
# On the Pi, over SSH:
git clone <your-fork-url> ~/wta-daily
cd ~/wta-daily
bash deploy/bootstrap_pi.sh      # creates .venv/, installs deps, copies config/.env templates
nano config/config.yaml          # adjust top_n, providers, theme, etc.
nano .env                        # add ELEVENLABS_API_KEY / OPENAI_API_KEY only if you enable those features

# Try one run by hand before scheduling it:
.venv/bin/python -m wta_daily.cli --config config/config.yaml --verbose
```

To pick up code changes later: `cd ~/wta-daily && git pull && bash deploy/bootstrap_pi.sh`
(safe/idempotent - it reuses the existing venv and only installs what changed).

### Scheduling it unattended (systemd, recommended)

Uses a **user-level** systemd service/timer, so it runs under your own
account with no root privileges and no system-wide unit files:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/wta-daily.service deploy/systemd/wta-daily.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now wta-daily.timer

# One-time only: let your user's systemd units keep running even when
# nobody is logged in over SSH (the normal state for a headless Pi). This
# is the only step that needs sudo, and it only affects your own account -
# it does not touch Pi-hole or any other system service.
sudo loginctl enable-linger "$USER"
```

Check on it later with `systemctl --user status wta-daily.timer` and
`journalctl --user -u wta-daily -f`.

The service file caps memory (`MemoryMax=768M`), CPU (`CPUQuota=200%`, i.e.
at most 2 of the Pi 4's 4 cores), and scheduling priority (`Nice=10`) so that
even a runaway run can never starve Pi-hole's DNS resolution on the same
2 GB Pi - see [`deploy/systemd/wta-daily.service`](deploy/systemd/wta-daily.service)
for the full rationale in comments.

Prefer cron instead? [`deploy/cron/wta-daily.cron`](deploy/cron/wta-daily.cron)
is a one-line drop-in for `crontab -e` that does the same thing.

### If you're staying on Raspberry Pi OS Bullseye / Python 3.9 for now

The package targets `>=3.11` because Python 3.9 reached end-of-life on
2025-10-31 (no further security patches) and current Pillow (>=12) has
already dropped 3.9 support, so `pip` would silently pin you to an aging
Pillow release. If a full reflash isn't an option right now, the least-bad
alternative is a **user-space Python 3.11+ via `pyenv`** (compiled once,
installed under `~/.pyenv`, never touching `/usr/bin/python3` or anything
Pi-hole/the OS relies on) with the project's venv built from that interpreter
instead of the system one. This works but adds a one-time ~30-60 minute
build and an interpreter you're responsible for updating yourself - a clean
OS reflash is the better long-term outcome if you can do it.

## Testing & code quality

Over 246 unit/integration tests cover models (including `DailyReport.match_target_date`
and `MatchLookupResult`'s confirmed-negative-vs-unresolved distinction, and
`FeaturedPlayerReport`'s never-fabricate-a-missing-fact behavior), movement
math (including the "unknown" vs "new"
distinction), country/flag resolution, config loading, the plugin registry,
snapshot persistence (including the wider-pool-metadata-without-affecting-
movement-history behavior), the sample providers, `MatchProvider`'s default
day-first fallback in isolation (`tests/test_match_provider_base.py`), the
`wta_official` match provider's date-recovery, day-first tournament scan
(including the "never falls back to an older match", timezone-normalization,
irrelevant-tour-level-skipping, and unresolved-vs-confirmed-negative
behaviors), and bye/walkover/doubles filtering logic (mocked HTTP - see
`tests/test_wta_official_match_provider.py`), the tournament-catalogue page
cache and per-endpoint `api_usage` instrumentation
(`tests/test_wta_api_client.py`), the `api_usage` request counter itself
(`tests/test_api_usage.py`), the `live_tennis_api` and `api_tennis` match
providers' name-resolution and event-status filtering logic (mocked HTTP -
`tests/test_live_tennis_api_match_provider.py`,
`tests/test_api_tennis_match_provider.py`), the `best_of` composite
provider's source-combination logic for both `get_latest_match` ("prefer the
more recently confirmed date") and `get_matches_for_date` ("only call a
later source for a player still genuinely unresolved, never one already
confirmed absent by an earlier source")
(`tests/test_best_of_match_provider.py`, including a regression test for the
real stale-namesake-record incident described above), the template script
generator (including the "mention movement
only when it changed", "never say a baseline run's players are new", "the
sign-off is always last", "no verbatim-identical script two days in a
row", and "the featured-player segment lands after the Top N and before
the sign-off, or not at all if disabled" behaviors), the featured-player
narration builder in isolation (`tests/test_featured_player_narration.py` -
pursuit vs. arrived vs. world-No.-1 framing, honest movement/match
reporting, the occasional-not-daily "#1 in our hearts" gate, and
substantial wording variation across many simulated days), graphics
rendering, and a full end-to-end pipeline run (including the
per-player-failure-isolation scenario, the "rankings fetched exactly once
per run, wider pool exposed for reuse" behavior, and the featured player's
every outside-Top-N/moving-toward-Top-N/steady/moving-down/win/loss/no-match/
match-unavailable/entered-Top-N/reached-No.-1/lookup-failure-isolated
scenario in `tests/test_pipeline_integration.py`), and the ElevenLabs
narration-pronunciation fixes (score normalization, pronunciation
dictionary create/cache/failure behavior, and the full synthesize() flow -
see "Narration pronunciation (ElevenLabs)" above) - all using the offline
`sample` providers, synthetic in-test providers, or mocked HTTP responses,
so `pytest` never makes a real network call.

```bash
pytest              # unit + integration tests
ruff check wta_daily tests
mypy wta_daily
```

## Roadmap

**Phase 1 (this repository, done):** rankings, movement, matches, `report.json`,
`script.txt`, `leaderboard.png`, `player_cards/*.png`, date-stamped output
folders, per-player error isolation, unit tests.

**Phase 2 (scaffolded, disabled by default - flip a config flag to try):**

- `voice.enabled: true` - ElevenLabs narration (`wta_daily/voice/elevenlabs_provider.py`).
- `video.enabled: true` - ffmpeg assembly into `video.mp4`, 1920x1080 H.264
  (`wta_daily/video/ffmpeg_assembler.py`) - already verified to produce a
  correct intro + leaderboard + player-card sequence with the narration
  track muxed in when present.
- `git.auto_commit` / `git.auto_push` - daily commit of `output/<date>/` plus
  the updated `data/*.json` history files (`wta_daily/git_automation.py`).
  **This never touches YouTube** - publishing remains a manual, human step.
- Scheduling wiring (cron/Task Scheduler/GitHub Actions examples above).

**Future modules** (each addable independently, per the plugin architecture
above): ATP version, Top 25, tournament previews, head-to-head stats, player
biographies, career milestones, injury reports, weather, historical ranking
charts, automatic YouTube description generation, thumbnail generation,
multi-language narration (Spanish, French, ...).
