# wta-daily

Automated, unattended generation of the **assets** for a daily YouTube video
covering the WTA Top N women's tennis rankings: rankings + movement, each
player's latest match, a narration script, broadcast-style graphics, and
(optionally) AI narration and a finished MP4. **Nothing is ever uploaded to
YouTube automatically unless you deliberately enable it** (`youtube.enabled:
true`) - the default, out-of-the-box behavior stops at "ready for you to
review," by design. See ["YouTube publishing"](#youtube-publishing) for the
fully optional, off-by-default Phase 3 that adds a real upload via the
official YouTube Data API v3.

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
narration, ffmpeg video assembly, git automation) and an opt-in **Phase 3**
(YouTube publishing) - all disabled by default. See ["Roadmap"](#roadmap) for
what's next.

---

## Table of contents

- [Data source research & recommendation](#data-source-research--recommendation)
- [Official ranking vs. daily match activity](#official-ranking-vs-daily-match-activity)
- [Understanding & optimizing API usage](#understanding--optimizing-api-usage)
- [Featured player (recurring editorial segment)](#featured-player-recurring-editorial-segment)
- [Slide timing synchronization](#slide-timing-synchronization)
- [YouTube publishing assets](#youtube-publishing-assets)
- [YouTube publishing (Phase 3: the actual upload)](#youtube-publishing)
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

## Official ranking vs. daily match activity

**The WTA does not recalculate its official ranking after every match.**
Players earn ranking points during a tournament, but the published
ranking list only updates on the WTA's own weekly publication schedule -
during an ongoing event, a player's official rank stays whatever the
current published list says, regardless of what she does that week. This
project's core architectural rule follows directly from that fact:

> **A player winning (or losing) a match must never, by itself, change the
> official Top N ranking order this app reports. Only an actual new
> official WTA ranking publication can do that.**

### The three concepts this project keeps separate

1. **Official ranking** - "#1 Aryna Sabalenka," "#3 Coco Gauff." Comes
   from `rankings_provider` (see above) and stays fixed until a newer
   official list is published. Every place in the app that says a player
   is "No. 1"/"No. 4" refers to this, unless explicitly labeled otherwise.
2. **Daily match activity** - "Coco Gauff, currently ranked No. 3,
   defeated X yesterday." Comes from `match_provider` and affects the
   day's *narration* (win/loss, opponent, score, tournament), never the
   ranking numbers.
3. **Projected/live ranking** *(not implemented - reserved for the
   future)* - an estimate of where in-progress tournament points might
   place a player on the *next* official list. See "Projected/live
   rankings" below for why this is deliberately not built yet, and how it
   would be labeled if it ever is.

### How this is enforced, not just assumed

`PlayerRanking.ranking_date` (`wta_daily/models.py`) carries the
publication date of the official list a rank/points value came from -
populated by `wta_official` from the upstream API's own `rankedAt` field
(present on every entry, identical across a whole response - confirmed
live: fetching the Top 10 twice in the same week returns the exact same
`rankedAt`, points, and ranks both times). `wta_daily.movement.compute_movement`
takes a `same_official_ranking_list` flag: whenever the current fetch and
the most recent saved snapshot are confirmed to be the *identical*
published list (`ranking_date` matches), movement is forced to `SAME` for
every previously-tracked player - **regardless of what the raw rank
numbers say**. This is deliberately defensive: the numbers *should*
already agree whenever the official list hasn't changed (that's what
"official" means), but a match result must never be able to produce
"moved up"/"moved down" narration, even in the face of a hypothetical
transient upstream inconsistency. `ranking_date` is `None` for a provider
that doesn't expose one (e.g. the offline `sample` fixture); in that case
the app safely falls back to comparing rank numbers directly, exactly as
it always has.

A genuinely new official publication (`ranking_date` differs from the
previous snapshot's) is treated completely differently - movement is then
computed normally from the rank numbers, and is expected to actually
change. See `tests/test_movement.py` and
`tests/test_pipeline_integration.py`'s "Official ranking vs. daily match
activity" section for the full regression suite, including the specific
scenario of a match win with an unchanged official list, a genuinely new
official list, and two consecutive days with the same list producing the
same ordering while still picking up fresh match results.

**Not a full rename.** `PlayerRanking`/`PlayerReport`/`FeaturedPlayerReport`
still use `rank`/`points` rather than `official_rank`/`official_ranking_points`
- renaming every reference across graphics, narration templates, and
`report.json`'s schema would be significant, purely cosmetic churn. The
distinction is made explicit instead through `ranking_date` (a field that
didn't exist before) and through each model's docstring stating plainly
that these values represent the officially published list and are never
recalculated from match results.

### Ranking points

If the rankings source provides official points, the app displays exactly
those - it never adds a match's ranking points on top of the official
total (confirmed by inspection: no code in `wta_daily/plugins/matches/`
touches `points` at all; match results and ranking data are fetched
through entirely separate provider interfaces and never merged at that
level).

### Narration wording

Because `movement` already carries the guarantee above, the narration
generator (`wta_daily/scripts_gen/template_generator.py`) and the
featured-player segment (`wta_daily/scripts_gen/featured_player.py`) both
describe ranking status and match results in **separate sentences**,
driven by two independent fields (`player.movement` and `player.match`):
a phrase like "climbs to world number {rank}" only ever gets selected when
`movement` is genuinely `UP`. `youtube_description.py`'s featured-player
"(up from No. Y)" annotation was previously computed by directly comparing
raw rank numbers - a second, independent path that bypassed the
`same_official_ranking_list` guarantee - and now reads `movement` instead,
so every "this changed" claim in the app funnels through the one place
that guarantee lives.

### Projected/live rankings (future feature, not implemented)

A genuinely different, interesting future feature: estimating where
in-progress tournament points might place a player on the *next* official
list. `rankings.projected_rankings_enabled` (`config.yaml`) exists as a
reserved, disabled-by-default placeholder for this - **setting it to
`true` currently raises a clear configuration error** rather than
silently doing nothing, since the feature isn't implemented (it would
need real logic to estimate provisional points from in-progress
tournament results, which the current data layer doesn't provide). If
it's ever built, the design requirement is that a projected number must
always be labeled as such (e.g. "projected No. 4" / "currently projected
to rise to No. 4") and must never be displayed or narrated as if it were
the official WTA ranking.

### Limitations - what can't be fully guaranteed

- **This all depends on `rankedAt` continuing to mean what it currently
  appears to mean.** `api.wtatennis.com` is an unofficial backend (see
  "Data source research" above) with no published contract - if a future
  response ever omitted `rankedAt` or changed its semantics, the app
  degrades safely (falls back to plain rank-number comparison, exactly
  the pre-`ranking_date` behavior) rather than failing, but the *extra*
  protection this feature adds would be unavailable until the field's
  behavior is reconfirmed.
- **A provider without a ranking date at all** gets none of this
  protection beyond what already existed (comparing numbers day to day) -
  this matters if a different `rankings_provider` is ever added that
  doesn't expose a publication date.
- **A same-day re-run isn't a new "publication."** If the pipeline is run
  twice in one day (e.g. a manual retry), both runs fetch the same
  official list and are correctly treated as unchanged - this is by
  design, not a limitation, but worth stating explicitly since "how many
  times has this run today" is not part of the freshness signal at all.

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

## Slide timing synchronization

Before this, `FfmpegVideoAssembler` used fixed slide durations (a fixed
intro, `video.seconds_per_player_card` for every player) regardless of how
much the narrator actually said about each one, so cuts happened at
arbitrary points relative to the spoken narration. Slides are now sized to
match the actual spoken narration whenever timing data is available,
falling back to the original fixed-duration behavior otherwise.

### 1-2. Options found, and whether ElevenLabs provides usable timing

ElevenLabs' text-to-speech API has a dedicated endpoint for exactly this:
`POST /v1/text-to-speech/{voice_id}/with-timestamps` (and a streaming
variant) - **the same generation as the standard endpoint**, just
returning character-level `alignment` (per-character start/end times in
seconds) alongside the base64-encoded audio in one JSON response, instead
of raw audio bytes. It accepts the exact same request body (`text`,
`model_id`, `voice_settings`, ...) as the plain endpoint and works with the
model this project already uses - nothing about it is restricted to a
higher plan tier, so switching to it doesn't cost anything the plain
endpoint didn't already cost.

### 3. Approaches compared

| # | Approach | Sync accuracy | ElevenLabs calls | Credit usage | Complexity | Reliability | Debuggability | Voice consistency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **ElevenLabs alignment from the one existing TTS request** (switch to `.../with-timestamps`) | High - real per-character timing for the exact audio being played | **Same as today (1 call)** | **Same as today** | Low-moderate (map script paragraphs to alignment offsets) | High - one request, one source of truth | High (see `narration_timing.json` below) | Unaffected - identical audio, one voice, one take |
| 2 | Synthesize each player's paragraph as a **separate** TTS request, use each clip's real duration | High | **~11-12x today's calls** for a Top 10 + featured segment | ~11-12x - real money/quota cost for a daily job | Moderate (stitch N audio clips instead of 1) | Lower - N requests means N chances to fail, and stitched clips can have audible seams | Moderate | **At risk** - separate generations of the same voice can vary subtly in pacing/pitch between segments |
| 3 | **Estimate timings from text length/word count** (no ElevenLabs data at all) | Low-moderate - real speech rate varies with punctuation, emphasis, and the words themselves, so this only approximates | 0 extra | 0 extra | Low | High (no network dependency) | Low (no ground truth to compare against) | Unaffected |
| 4 | (This project's choice) **#1** | High | Same as today | Same as today | Low-moderate | High | High | Unaffected |

Approach 2 was ruled out specifically because the task calls for avoiding
unnecessary ElevenLabs calls/credit usage - it multiplies both for a
purely mechanical benefit (exact per-clip duration) that approach 1
already provides for free. Approach 3 was kept in mind as the *fallback*
this project already needed anyway (for when narration is disabled, or
ElevenLabs doesn't return alignment for some reason) - see below - but not
as the primary mechanism, since real timing metadata should be preferred
over estimation whenever it's available.

### 4. API-call / credit impact

**Zero.** `ElevenLabsVoiceSynthesizer.synthesize` already made exactly one
`POST` per run; it now points at `.../with-timestamps` instead of the
plain endpoint for that same one call, and decodes `audio_base64` instead
of reading a raw byte stream - otherwise unchanged (same `text`,
`model_id`, and `voice_settings` as before).

### 5-6. What changed, and how slide timings are determined

- **`wta_daily/voice/narration_timing.py`** (new): given a `DailyReport`,
  the exact `script.txt` text, and ElevenLabs' character alignment, derives
  one `NarrationSegment` per visual:
  1. Splits `script.txt` into its blank-line-separated paragraphs (the
     same structure both `TemplateScriptGenerator` and the `openai`
     generator's system prompt already produce: an intro, one paragraph
     per Top N player in rank order, optionally the featured-player
     segment, then a single closing sign-off).
  2. Matches each middle paragraph to the next expected player (by
     rank order) or the featured player (checking whether her name
     appears in it) - a paragraph that matches nobody (e.g. the template
     generator's length-padding filler sentence) extends the *previous*
     matched segment instead of becoming its own cut.
  3. Looks up each paragraph's start/end time directly in the alignment
     (which is for `script.txt`'s own characters, since nothing
     transforms the text before it's sent to ElevenLabs).
  4. Extends the final (sign-off) segment to the alignment's true last
     character end-time, so the silent video's total length is never
     shorter than the actual narration - see `FfmpegVideoAssembler`'s
     docstring for why a short silent video would otherwise truncate the
     audio via ffmpeg's `-shortest` mux flag.
  Writes the result to **`narration_timing.json`** (see below) - useful on
  its own for debugging, and is what decouples "how do we interpret
  alignment data" from "how do we build a video", so a future non-FFmpeg
  video assembler could reuse the same file.
- **`wta_daily/voice/elevenlabs_provider.py`**: uses the
  `.../with-timestamps` endpoint; `synthesize()` gained an optional
  `report` parameter (see `VoiceSynthesizer.synthesize`'s updated
  signature in `wta_daily/plugins/base.py`) so it can compute and write
  `narration_timing.json` as a byproduct - any failure while doing so is
  caught and logged, never raised, since timing metadata is a quality
  improvement, not a requirement for narration to succeed.
- **`wta_daily/video/ffmpeg_assembler.py`**: reads `narration_timing.json`
  (via `DailyOutputStore.timing_path`) if it exists and is usable; builds
  one slide per segment (leaderboard for intro/closer, each player's card
  for her segment, `DailyOutputStore.featured_card_path` for the featured
  segment *if that file exists*, else the leaderboard - no dedicated
  featured-player graphic is generated by this change, matching the
  featured-player feature's own explicit "graphics are out of scope for
  now" decision, but the lookup is already wired up for whenever one is
  added). A missing player card falls back to the leaderboard for that
  specific segment rather than skipping it (keeps every later cut point
  aligned with the narration); consecutive slides that end up showing the
  identical image (e.g. two leaderboard fallbacks in a row) are merged
  into one longer slide rather than an unnecessary hard cut to the same
  picture. If no usable timing file exists at all (narration disabled, or
  ElevenLabs didn't return alignment), this falls back to exactly the
  previous fixed-duration behavior, including a new fixed-duration slide
  for the featured player (previously not handled in that fallback path).
- **`wta_daily/persistence/report_store.py`**: `DailyOutputStore` gained
  `timing_path` (`narration_timing.json`) and `featured_card_path`
  (`featured_player.png`, currently never produced by any renderer)
  properties.

**Sample timing breakdown** (real Top 10 + Emma Navarro data, August 16,
2026 run - narration simulated at a fixed ~150-words-per-minute character
rate for this demonstration since no ElevenLabs credentials were available
in this environment; the *mechanism* - script parsing, paragraph matching,
segment derivation - is exactly what runs against a real alignment
response):

```text
Kind      Label                          Start     End  Duration
intro     intro                           0.00    4.40      4.40
player    Aryna Sabalenka                 4.47   10.67      6.20   (no match)
player    Elena Rybakina                 10.67   22.08     11.41   (no match + points-gap sentence)
player    Jessica Pegula                 22.08   32.35     10.27   (won 6-3,6-2)
player    Coco Gauff                     32.35   39.09      6.74   (no match)
player    Iga Swiatek                    39.09   47.56      8.47   (no match)
player    Mirra Andreeva                 47.56   58.43     10.87   (no match + points-gap sentence)
player    Karolina Muchova               58.43   69.30     10.87   (no match + points-gap sentence)
player    Linda Noskova                  69.30   83.31     14.01   (won 6-3,6-3 + points-gap sentence)
player    Elina Svitolina                83.31   92.71      9.40   (no match + points-gap sentence)
player    Amanda Anisimova               92.71  117.26     24.55   (won 6-2,6-3 + points-gap + filler)
featured  Emma Navarro                  117.26  137.14     19.88   (won 3-6,6-4,6-2)
closer    closer                        137.14  144.01      6.87
```

Note the variation this produces automatically - Sabalenka's simple "did
not play" blurb (6.2s) versus Anisimova's match-result-plus-points-gap
paragraph, which also absorbed the length-padding filler sentence
(24.55s) - **never a uniform division of the total**, exactly per the
task's explicit requirement.

This was verified against a **real** rendered video: the simulated
alignment above drove a real silent track of the same total duration
through `ffmpeg`, and extracting a video frame partway into each segment
and perceptually hashing it against every source PNG confirmed an exact
match for the leaderboard (intro/closer) and every player card checked -
i.e. slide transitions really do land inside their intended narration
segment, not just in the timing math. Final `video.mp4` duration (~144.0s)
matched the simulated `narration.mp3` (~144.0s) to within a single video
frame, with a full audio track and no perceptible blank tail.

### 7. Remaining limitations

- **Paragraph-to-player matching is structural, not guaranteed by a formal
  contract.** It relies on the convention (true for both shipped script
  generators today) that paragraphs appear in rank order, one per player,
  with the featured player (if any) last. A future script generator that
  breaks this convention (e.g. combines two players into one paragraph)
  would silently fall back to "no usable timing" for that run (an empty
  segment list - `compute_segment_timings` never mismatches players, it
  just gives up cleanly) rather than mis-synchronizing.
- **No dedicated featured-player visual exists yet** - the lookup for one
  (`DailyOutputStore.featured_card_path`) is wired up, but until a future
  graphics change actually renders that file, her segment always shows the
  leaderboard, per the task's own "otherwise use the leaderboard" fallback
  guidance.
- **Not frame-perfect lip-sync** - by design, per the task's own scope
  ("we do not need frame-perfect lip-sync... slide changes correspond
  naturally to the spoken sections"). Character-level alignment is
  precise, but paragraph-boundary matching (not word-level matching within
  a paragraph) is the unit of granularity for slide changes.
- **Verified live using a simulated alignment**, not a real ElevenLabs
  response, since no ElevenLabs API credentials were available in this
  environment - the request/response shapes and decoding match
  ElevenLabs' documented `with-timestamps` contract exactly (see
  `tests/test_elevenlabs_provider.py`), but a first real run against a
  live account is worth spot-checking once credentials are available.

## YouTube publishing assets

Three artifacts a human would otherwise assemble by hand when uploading the
day's video - all built purely from the same validated `DailyReport`
already produced for `report.json`/narration, so none of them cost an
extra external API call. On by default (`publishing.thumbnail_enabled` /
`publishing.description_enabled`, both `true`); the featured-player card
has no separate toggle - it follows `featured_player.enabled` directly
(see below).

### Featured-player card (`output/<date>/featured_player.png`)

The narration already had a closing featured-player segment (see
["Featured player"](#featured-player-recurring-editorial-segment)), but
the video had no matching visual for it - the previous slide just stayed
on screen for however long that segment happened to run. `wta_daily/graphics/featured_card.py`
renders a dedicated card, reusing the exact building blocks
`wta_daily/graphics/player_card.py` uses (fonts, theme colors, flag
rendering, the shared `movement_headline_text` helper extracted from that
module into `wta_daily/graphics/utils.py`, and the same "YESTERDAY'S
MATCH" panel layout) so it reads as part of the same show - with one
deliberate difference: instead of a giant `#{rank}` headline, it leads
with a filled "FEATURED PLAYER" pill, so it's unmistakably a bonus segment
rather than an eleventh Top N entry, even at a glance.

Nothing about this is Emma-specific - the player comes from
`report.featured_player` (itself built from `FeaturedPlayerConfig`, see
that section above), never hard-coded. Every fact shown (rank, points,
movement, match result) comes straight off that model; if her rank
couldn't be resolved this run, the card is simply **not rendered** at all
(there's no honest visual to draw without at least a rank) rather than
showing a blank or fabricated one - the pipeline logs this and moves on,
exactly like every other featured-player failure mode.

**Video integration**: this reuses the exact mechanism already built for
slide-timing synchronization (see ["Slide timing
synchronization"](#slide-timing-synchronization)) - `FfmpegVideoAssembler`
already checked for a file at `DailyOutputStore.featured_card_path` and
fell back to the leaderboard when it didn't exist, specifically so that a
future graphics addition could "drop a PNG here with no further code
changes." That's exactly what this is: no changes to
`wta_daily/video/ffmpeg_assembler.py` or
`wta_daily/voice/narration_timing.py` were needed at all. The card shows
for exactly the real, alignment-derived duration of her narration segment,
and this keeps working unchanged if the configured featured player
changes, since the whole path is keyed off the `featured` segment kind and
a fixed filename convention - never a hard-coded name.

### YouTube thumbnail (`output/<date>/thumbnail.png`, 1280x720)

`wta_daily/graphics/thumbnail.py` renders a deliberately much simpler,
bolder graphic than the leaderboard - 2-3 huge lines of text ("WTA TOP
{n}", the date, and the tournament if one is confirmed) on a plain
background, sized to read at YouTube-feed thumbnail size. Reuses the
project's theme colors/fonts, but is a fixed 1280x720 canvas independent
of `graphics.width`/`height` (which size the much larger leaderboard/card
images). The headline font shrinks automatically if a longer tour name or
larger `top_n` (e.g. "TOP 25") would otherwise overflow the frame.

The tournament line uses `wta_daily.tournament_context.most_relevant_tournament`
(see below) and is simply omitted - not guessed - on a day with no
reliable signal. The featured player is deliberately **never** added to
the thumbnail just because one is configured - the thumbnail represents
the actual daily Top N video, and the ten numbered rankings rows/stats
that don't belong on it stay off it too, per the brief's own "avoid
overcrowding" and "don't add the featured player merely because one is
configured" guidance.

### YouTube description (`output/<date>/youtube_description.txt`)

`wta_daily/youtube_description.py` is a small pure function (not a
plugin - there's exactly one sensible way to do this today, so this
skips the registry machinery used for genuinely interchangeable
concerns) that builds a plain-text description: a dated headline, one
sentence naming the tournament (again via `most_relevant_tournament`,
omitted the same way if there's no reliable signal), the numbered Top N
list straight from `report.players`, an optional "Featured Player" blurb
(only when a featured player is configured *and* her rank was resolved
this run - one factual sentence built only from fields that are actually
populated, e.g. her real rank and, if she played, the real opponent/score/
tournament), and a generic closing line. No fake URLs, handles, sponsors,
or calls to action - none are configured anywhere in this project, so none
appear.

### `most_relevant_tournament` (`wta_daily/tournament_context.py`)

Both the thumbnail and the description need to answer "what tournament is
this update about" - answered once, in one shared function, from data
*already fetched* for the day's report: the tournament name most of
`report.players[*].match.tournament` (plus the featured player's match, if
any) agree on. No hard-coded tournament calendar, no extra lookup - a day
where nobody in the tracked group played returns `None`, and both callers
handle that by omitting the tournament reference rather than reusing a
stale one or guessing.

### API-call impact

**None.** All three artifacts are generated from the `DailyReport` object
already in memory by the time graphics rendering runs - no new
`RankingsProvider`/`MatchProvider` calls anywhere in this feature.
Verified live: the `wta_daily.api_usage` summary (see ["Understanding &
optimizing API usage"](#understanding--optimizing-api-usage)) reported the
exact same call counts (2 rankings, 26 tournament discovery, 1 match
results = 29 total, for a run with the featured player enabled) before
and after adding these three artifacts.

## YouTube publishing

**Optional, off by default** (`youtube.enabled: false`). This is the one
feature in the project that has a real, external, user-visible side effect
(a public/unlisted/private video appearing on a real YouTube channel), so
it gets its own explicit opt-in, its own duplicate-upload protection, and
its own "never touch a successfully generated local artifact" guarantee -
on top of the config-level default every other Phase 2/3 feature already
gets.

**While `youtube.enabled` is `false` (the default), nothing changes about
how this project behaves today.** Concretely: the optional
`google-api-python-client`/`google-auth-oauthlib` packages are never
required, no OAuth credential file is ever read, no network call to Google
is ever made, and no upload is ever attempted - the rest of the pipeline
runs exactly as it did before this feature existed. (`wta_daily/youtube/`
itself - a small, dependency-free Python package - is still imported by
the pipeline/CLI the same way any other internal module is; what matters,
and what's actually guaranteed, is the list above, not whether that one
lightweight import happens.) This is enforced structurally, not just by
convention: every `google-api-python-client`/`google-auth-oauthlib` import
is deferred inside a function body (see `wta_daily/youtube/uploader.py`'s
module docstring), and `publish_report()` (the single entry point) checks
`config.enabled` before doing anything else at all.

### The video title (`output/<date>/title.txt`)

`wta_daily/title.py` is a single, deterministic, canonical function -
`generate_title(report)` - producing exactly:

```text
WTA Top 10 Update — August 17, 2026
```

`{top_n}` comes from `len(report.players)` (not a hard-coded "10"), and the
date comes from `report.report_date` - the pipeline's own canonical "what
day is this for" field, never the system clock - so re-publishing an older
report with `--upload-youtube` (below) always titles it correctly. No LLM
call: the format is fixed, so there's nothing to generate creatively.
Written alongside every other daily artifact (on by default, no toggle -
it costs nothing to produce), and it's the same string
`wta_daily/youtube/uploader.py` sends to the YouTube Data API as the
video's title, so there is exactly one place this format is defined.

### One-time Google Cloud setup

Before you can enable this feature at all:

1. Create (or reuse) a project at the
   [Google Cloud Console](https://console.cloud.google.com/).
2. **APIs & Services -> Library** -> enable **YouTube Data API v3**.
3. **APIs & Services -> OAuth consent screen** -> configure it (External is
   fine for a personal channel).
4. **APIs & Services -> Credentials -> Create Credentials -> OAuth client
   ID** -> Application type **Desktop app**. Download the resulting JSON.
5. Save that file as `secrets/youtube_client_secret.json` (the default
   `youtube.client_secret_path` - see `config.example.yaml`). The `secrets/`
   directory is git-ignored (see `.gitignore`) - **never commit this file**,
   and never commit `secrets/youtube_token.json` either once it exists (see
   below) - both contain credentials capable of uploading to your channel.

**Before relying on this for unattended daily uploads, read "Testing vs.
production: avoiding a 7-day token expiry" below.** A consent screen left
in its default "Testing" state works fine for trying the feature out, but
will silently break an unattended Pi schedule about a week in.

### Initial interactive authorization (once, by hand)

The very first time YouTube publishing runs with no cached token yet,
`wta_daily/youtube/auth.py` opens a real OAuth consent screen in a browser
(`InstalledAppFlow.run_local_server(port=0)`) and grants only the narrow
`youtube.upload` scope. `port=0` deliberately asks the OS for whichever
local port happens to be free, printing the actual `http://localhost:<port>/`
redirect URL it's listening on to the console - there is no fixed port to
rely on.

That makes a **headless Raspberry Pi over SSH** awkward to authorize
directly (you'd have to read the just-in-time port from the Pi's console
output and forward exactly that port for that one run). The recommended
approach for this project instead is:

**Run the one-time authorization on a machine with a browser** - a laptop
checkout of the same repo (or WSL, if you're on Windows), using the same
`secrets/youtube_client_secret.json` - then securely copy (`scp`) the
resulting `secrets/youtube_token.json` over to the Pi's `secrets/`
directory. Nothing about the token file is Pi-specific, so this works
cleanly.

If you'd still rather authorize directly on the Pi over SSH, forwarding
the dynamic port is possible but more fiddly: start the auth attempt on
the Pi, note the exact port number printed in the `http://localhost:<port>/...`
URL it prints, then **in a separate terminal** open
`ssh -L <that-port>:localhost:<that-port> pi@<host>` and finish the flow
in your local browser - the port will very likely differ between runs, so
there's no single command to save and reuse.

Either way, run one upload by hand first (see "Testing an upload" below) -
that's what actually triggers this flow. Once it succeeds, you're done with
this step permanently (until you revoke/rotate credentials, or your
consent screen's publishing status forces re-authorization - see next).

### Where the token lives, and how unattended refresh works

The resulting OAuth token (including its long-lived refresh token) is
cached at `secrets/youtube_token.json` (the default `youtube.token_path`) -
also git-ignored, **never commit it either** (like the client secret, it's
a credential capable of uploading to your channel - see "Protecting the
token file" below for the file-permission hardening this project applies
automatically). Every later call - including every unattended scheduled
run on the Pi - loads this cached token and, if the short-lived access
token has expired, silently refreshes it via
`google.auth.transport.requests.Request()` and re-caches the result, with
no browser and no human involved. If the refresh token itself stops
working - revoked by hand in your Google Account settings, or expired per
"Testing vs. production" immediately below - the next run raises a clear
`YouTubeAuthError` explaining that the interactive authorization needs to
be repeated - it never crashes with a bare stack trace, and it never logs
the token/client-secret contents themselves (see "Logging" below).

### Testing vs. production: avoiding a 7-day token expiry

**This matters for the project's actual goal** - a Pi that uploads a video
every morning with no human involved - so read it before you walk away
from a working setup.

A freshly created Google Cloud OAuth consent screen starts in **Testing**
publishing status. That's perfectly fine for initially configuring and
testing this integration (everything in "Testing an upload" above works
normally), but Google enforces a hard rule for apps left in Testing:
**refresh tokens issued while a consent screen is in Testing status expire
after about 7 days**, regardless of how often they're used. That would
mean the very first unattended run more than a week after you authorized
would fail with `YouTubeAuthError`, needing you to notice, SSH in, and
redo the interactive authorization - exactly the outcome unattended
publishing is supposed to avoid.

**The fix**: once you're happy with a few test uploads, go to **APIs &
Services -> OAuth consent screen** (Google Cloud Console) and change the
app's **publishing status from Testing to "In production"** (the
**Publish App** button) - then re-run the interactive authorization once
more so the newly issued token isn't subject to the 7-day Testing-mode
limit. This is a small, one-time console setting, separate from writing
any code here.

**"In production" is not the same thing as Google's full app
verification** - it's worth being precise about the difference:

- **Publishing status (Testing vs. In production)** is what controls the
  7-day refresh-token expiry described above. Moving to "In production"
  by itself does not require submitting your app for Google's review.
- **Verification** is a separate, optional-for-many-cases review process
  Google may require for certain scopes/audiences (e.g. sensitive or
  restricted scopes requested by apps used by many external users, or
  apps that want their name/logo shown on the consent screen without a
  warning). For a personal project like this one - a single Google
  account (yours) authorizing its own single-purpose app for a narrow
  upload-only scope - you can typically move to "In production" and keep
  using it indefinitely as your own test user without completing full
  verification; you'll still see Google's "unverified app" warning during
  consent, which is expected and safe to click through for your own
  app/your own channel (do not confuse this cosmetic warning with the
  7-day token-expiry issue - they're different Google policies).
- Google's own requirements here can change over time and depend on
  exactly which scopes/audience you configure, so treat this section as
  "what to expect and where to look," not a permanent guarantee - if
  Google's console flags anything unexpected for your specific project,
  follow its guidance directly.

### Protecting the token file

`secrets/youtube_token.json` contains a refresh token capable of
authorizing uploads to your channel indefinitely, so both it and
`secrets/youtube_client_secret.json` are treated as sensitive credentials
- **never commit either file to git** (both live under the git-ignored
`secrets/` directory - see `.gitignore`).

On top of that, every time this project writes or refreshes the token file
(`wta_daily/youtube/auth.py`'s `_save_token`), it also restricts the
file's permissions to the owning user only (`chmod 600`, i.e.
`-rw-------`) on POSIX systems (Linux/macOS, including the Raspberry Pi).
This is applied automatically - there is nothing to configure - and is
best-effort: if `chmod` itself fails for some reason (e.g. an unusual
filesystem), it's logged as a warning rather than aborting the run, since
having written the token successfully matters more than this hardening
step succeeding. On Windows, this step is skipped entirely (Unix
permission bits don't apply there), which never causes a failure -
Windows development is unaffected either way.

### Testing an upload as `private` or `unlisted`

Set `youtube.privacy: unlisted` (the default) or `private` in
`config.yaml` **before you ever enable this feature**, and only switch to
`public` once you've confirmed a few uploads look right. To test the
publishing step **on its own**, without spending any rankings/match/
narration/video work or API calls:

```bash
pip install -r requirements-youtube.txt   # or: pip install -e ".[youtube]"

# Generate a day's assets normally first (as many times as you like, with
# youtube.enabled still false - nothing gets uploaded during this step):
python -m wta_daily.cli --config config/config.yaml --date 2026-08-17

# Then flip youtube.enabled: true in config.yaml, and publish that
# already-generated output/2026-08-17/ folder on its own:
python -m wta_daily.cli --config config/config.yaml --date 2026-08-17 --upload-youtube
```

`--upload-youtube` reloads the exact `report.json` already written for that
date and calls `wta_daily.youtube.uploader.publish_report()` directly - it
never constructs a `DailyPipeline`, so it can't re-fetch rankings, re-hit
any match API, re-synthesize narration, or re-render video/graphics. It
uses `output/<date>/video.mp4`, `thumbnail.png`, and
`youtube_description.txt` exactly as they already are on disk.

### Enabling automatic uploads

Once you're satisfied with a few manual `--upload-youtube` tests, set
`youtube.enabled: true` in `config.yaml` (leave `privacy` at `unlisted`
until you're ready for `public`). From then on, every normal scheduled run
(`python -m wta_daily.cli --config config/config.yaml`) publishes that
day's video as the final step, automatically - see "Pipeline ordering"
below for exactly when.

### Duplicate-upload protection

Every successful upload is recorded in `data/youtube-uploads.json` (see
`wta_daily/persistence/youtube_upload_store.py` - the same
write-to-temp-then-rename-atomically pattern as `rankings-history.json`),
keyed by `(report_date, tour)`, storing the video ID, URL, title, and
upload timestamp. Before uploading, `publish_report()` checks this file
first; if that date was already published successfully, it logs:

```text
YouTube upload skipped: report for 2026-08-17 already uploaded as <video ID>
```

and returns without calling the YouTube API at all - this is what makes a
re-triggered/duplicate scheduler run (or an accidental second manual run)
for the same date safe by default.

### Retrying a failed upload, or forcing a re-upload

A failed upload (network error, expired/revoked credentials, quota
exceeded, etc.) is **not** recorded as successful, so simply re-running
`--upload-youtube` for that date retries it normally - no special flag
needed, since only a *successful* upload is ever recorded.

To deliberately re-publish a date that already succeeded (e.g. you
re-rendered the video and want the new cut live), pass
`--force-youtube-upload` alongside `--upload-youtube`:

```bash
python -m wta_daily.cli --config config/config.yaml --date 2026-08-17 --upload-youtube --force-youtube-upload
```

This uploads a **new** video (YouTube has no "replace the video file"
endpoint via this API) and overwrites that date's record in
`youtube-uploads.json` with the new video's ID/URL - it does not delete or
unlist the previous upload for you.

### Pipeline ordering and failure isolation

Phase 3 always runs **last**, strictly after video assembly (Phase 2), and
only ever *consumes* artifacts already produced by earlier phases - it
never regenerates `video.mp4`, `thumbnail.png`, or
`youtube_description.txt` itself:

```text
Phase 1: rankings/movement/matches -> report.json / script.txt / title.txt
Phase 2: narration / graphics / video.mp4  (each independently optional)
Phase 3: YouTube publishing               (optional, off by default, always last)
```

A YouTube failure is isolated exactly like every other optional phase's
failure (see ["Error handling & logging"](#error-handling--logging)): it's
appended to `report.json`'s `errors` list and logged clearly, but it never
raises out of `DailyPipeline.run()`, never deletes/regenerates
`video.mp4` or any other artifact, and never re-attempts the video upload
just because a *separate* step (the thumbnail) failed:

```text
YouTube video upload: SUCCESS
YouTube video ID: abc123
Thumbnail upload: FAILED
```

is reported as a **successful** publish (the video is live) with a
distinct thumbnail-specific error - `result.thumbnail_error` - rather than
as an overall failure, and the successful video upload is still recorded
for duplicate protection.

### Logging

```text
YouTube publishing enabled
Uploading video...
Video uploaded successfully
YouTube video ID: abc123
YouTube URL: https://www.youtube.com/watch?v=abc123
Uploading custom thumbnail...
Thumbnail uploaded successfully
```

Client secrets, access tokens, refresh tokens, and authorization headers
are **never** logged - `wta_daily/youtube/auth.py` only ever logs file
paths and high-level status (see `tests/test_youtube_auth.py::test_get_credentials_never_logs_the_token_value`).
While disabled, the only output is a single debug-level line
(`YouTube publishing is disabled...`) - no warnings, since a missing
credential file is completely expected and correct in the default state.

### API-call impact

**None to the WTA/tennis data sources.** Phase 3 makes exactly one YouTube
Data API video-insert call plus (if a thumbnail was generated) one
thumbnail-set call per successful publish - it never touches
`RankingsProvider`/`MatchProvider` and isn't counted by
`wta_daily.api_usage` (a separate, Google-specific quota - see
"Dependencies" below for the packages this uses).

### Dependencies

The official `google-api-python-client` / `google-auth-oauthlib` /
`google-auth-httplib2` packages - **never** Selenium, browser automation,
or YouTube Studio scripting. Intentionally kept out of the base
`requirements.txt` (unlike the plain-`requests`-based ElevenLabs/OpenAI
integrations) since they're a real, additional install footprint that most
installs - anyone leaving `youtube.enabled: false` - never need:

```bash
pip install -r requirements-youtube.txt
# or:
pip install -e ".[youtube]"
```

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
requires 3.10+). `ffmpeg` is only needed if you enable video assembly, and
`pip install -r requirements-youtube.txt` is only needed if you enable
YouTube publishing (see ["YouTube publishing"](#youtube-publishing)) - both
stay off by default. For development on Windows via Cursor, any 3.11+
interpreter works fine; this is just for local dev - see the Raspberry Pi
section for the production deployment steps (`deploy/bootstrap_pi.sh` etc.).

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
    title.txt
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
- `rankings.projected_rankings_enabled` - reserved, disabled-by-default
  placeholder for a future live/projected-ranking feature; setting it to
  `true` raises a configuration error today (not implemented). See
  ["Official ranking vs. daily match activity"](#official-ranking-vs-daily-match-activity) above.
- `featured_player` - the recurring "America's favorite" Emma Navarro
  segment; `enabled: false` by default. See ["Featured player"](#featured-player-recurring-editorial-segment) above.
- `script.generator` - `template` (default, offline, free) or `openai`
  (requires `OPENAI_API_KEY`).
- `graphics.theme` - all colors, plus optional custom font paths.
- `voice` / `video` / `git` - Phase 2 features, all `enabled: false` by
  default.
- `publishing.thumbnail_enabled` / `publishing.description_enabled` -
  YouTube thumbnail + description, both `true` by default (they cost no
  extra API calls - see ["YouTube publishing assets"](#youtube-publishing-assets)).
- `youtube.enabled` - the actual Phase 3 upload to YouTube via the official
  Data API v3; `false` by default. See ["YouTube publishing"](#youtube-publishing)
  above for the one-time Google Cloud setup this needs before enabling it.

**Secrets are never stored in the config file.** Each secret-consuming
setting is a `..._env` field naming an *environment variable* (see
[`.env.example`](.env.example)); the actual key is resolved from the process
environment (a local `.env` file via `python-dotenv`, your shell, or your
CI/scheduler's secret store) at run time. `wta_daily/config.py` raises a
clear `ConfigurationError` if a feature is enabled but its key is missing -
it never silently sends an empty key or hardcodes a placeholder. YouTube's
OAuth credentials are the one exception to the "`..._env` variable" pattern
- they're small JSON *files* (a client secret plus an auto-refreshing
token), not a single bearer key, so `youtube.client_secret_path` /
`youtube.token_path` name git-ignored file locations instead (see
["YouTube publishing"](#youtube-publishing)).

## Folder structure

```text
wta-daily/
    wta_daily/              # the installable Python package (see below)
    data/
        rankings-history.json   # append-only daily snapshots, for movement comparison
        players.json             # small player_id -> {name, country_code} cache
        youtube-uploads.json     # only if youtube.enabled was ever true - duplicate-upload protection
        sample/                   # offline fixtures used by tests/demos
        cache/                    # scratch space for provider-level caching
    output/
        2026-08-09/              # one self-contained folder per day
            report.json
            script.txt
            title.txt               # canonical YouTube video title (wta_daily/title.py)
            narration.mp3          # Phase 2, only if voice.enabled
            narration_timing.json  # only if voice.enabled and ElevenLabs returned alignment
            leaderboard.png
            player_cards/
            featured_player.png    # only if featured_player.enabled and her rank resolved
            thumbnail.png          # 1280x720, on by default (publishing.thumbnail_enabled)
            youtube_description.txt  # on by default (publishing.description_enabled)
            video.mp4              # Phase 2, only if video.enabled
    secrets/                  # YouTube OAuth client secret / cached token - git-ignored, see below
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
          + wta_daily.title.generate_title()      (title.txt - one canonical, deterministic function)
       7. GraphicsRenderer.render_*()           <- plugin: graphics_registry
       8. [optional] VoiceSynthesizer.synthesize()  <- plugin: voice_registry
       9. [optional] VideoAssembler.assemble()      <- plugin: video_registry
      10. [optional, off by default] wta_daily.youtube.uploader.publish_report()  (Phase 3 - see below)
      11. [optional] git_automation.commit_and_push()
```

Every numbered step other than movement/persistence/title/YouTube is a
**plugin**: a small abstract base class in `wta_daily/plugins/base.py`
(`RankingsProvider`, `MatchProvider`, `ScriptGenerator`, `GraphicsRenderer`,
`VoiceSynthesizer`, `VideoAssembler`). Concrete implementations register
themselves with a decorator against one of the registries in
`wta_daily/plugins/registry.py`. Step 10 (YouTube publishing) is
deliberately **not** a plugin - like `wta_daily/git_automation.py`, there's
exactly one real implementation (the official YouTube Data API v3) for this
concern, so it's a single, optional, config-gated module rather than
registry machinery; see ["YouTube publishing"](#youtube-publishing) for the
full design (disabled-by-default guarantee, failure isolation, duplicate
protection).

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
- **A YouTube publishing failure (Phase 3) never touches any local
  artifact.** `wta_daily.youtube.uploader.publish_report()` catches any
  exception from the upload/thumbnail calls, records it on
  `YouTubePublishResult` instead of raising, and `DailyPipeline` appends a
  clear message to `report.json`'s `errors` - the already-generated
  `video.mp4`, `thumbnail.png`, `youtube_description.txt`, and `report.json`
  are never deleted or regenerated because of it. A thumbnail failure after
  a successful video upload is reported as its own distinct error, not
  merged into (or mistaken for) an overall failure. See ["YouTube
  publishing"](#youtube-publishing) above and
  `tests/test_youtube_uploader.py`.

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

If you also want YouTube publishing on the Pi (optional - see ["YouTube
publishing"](#youtube-publishing) for the full setup): `.venv/bin/pip
install -r requirements-youtube.txt`, place
`secrets/youtube_client_secret.json` on the Pi, then run the one-time
interactive authorization either via SSH port forwarding
(`ssh -L 8080:localhost:8080 pi@<host>`) or by running it once on a
machine with a browser and copying the resulting `secrets/youtube_token.json`
over - both `secrets/*` files are git-ignored, so `git pull` never touches
them.

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

Over 360 unit/integration tests cover models (including `DailyReport.match_target_date`,
`DailyReport.ranking_date`/`PlayerRanking.ranking_date`'s round-trip and
legacy-data-without-the-field defaulting, and `MatchLookupResult`'s
confirmed-negative-vs-unresolved distinction, and
`FeaturedPlayerReport`'s never-fabricate-a-missing-fact behavior), movement
math (including the "unknown" vs "new" distinction, and the
`same_official_ranking_list` guarantee that a match result can never
imply a ranking change - `tests/test_movement.py`), the `wta_official`
rankings provider's `rankedAt` parsing
(`tests/test_wta_official_rankings_provider.py`), a dedicated
"Official ranking vs. daily match activity" scenario suite in
`tests/test_pipeline_integration.py` (a daily win leaving official ranks
unchanged, a genuinely new official publication updating them correctly,
narration never claiming a ranking change from a match alone, and two
consecutive days with the same official list producing the same ordering
while still picking up fresh match results), country/flag resolution,
config loading, the plugin registry,
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
scenario in `tests/test_pipeline_integration.py`), and the slide-timing
synchronization work (`tests/test_narration_timing.py` - paragraph
matching, featured-player and filler-paragraph handling, malformed-input
fallback; `tests/test_elevenlabs_provider.py` - the with-timestamps
endpoint and narration-timing byproduct; `tests/test_ffmpeg_assembler.py`
- timing-based vs. fixed-duration slide selection, missing-card and
missing-featured-visual fallback, and video assembly succeeding both with
and without narration), and the YouTube publishing assets
(`tests/test_tournament_context.py` - relevant-tournament inference
including ties and no-signal days; `tests/test_youtube_description.py` -
date/Top-N/tournament/featured-player content, no fabricated data, no
URLs/handles/CTAs; new cases in `tests/test_graphics.py` for the featured
card and the 1280x720 thumbnail; and pipeline-level cases in
`tests/test_pipeline_integration.py` for the featured card appearing
across every featured-player scenario, being picked up by the real
`FfmpegVideoAssembler` for its narration segment, and both publishing
toggles), and YouTube publishing/Phase 3 (`tests/test_title.py` - the exact
title format across month/day/year-boundary/player-count cases;
`tests/test_youtube_upload_store.py` - the duplicate-protection JSON store;
`tests/test_youtube_uploader.py` - `publish_report`'s full orchestration
with a mocked client (disabled short-circuit, successful upload +
thumbnail, duplicate skip, `--force` re-upload, missing-video/upload/
thumbnail failure isolation); `tests/test_youtube_auth.py` - OAuth
token reuse/refresh/error-handling using real (offline) `Credentials`
objects, skipped rather than failed if the optional Google packages aren't
installed; new cases in `tests/test_config.py` and
`tests/test_pipeline_integration.py` for `youtube.enabled`'s default-off
guarantee, error-isolation into `report.json`, and an end-to-end run
through the real `googleapiclient` `build()` call; and `tests/test_cli.py`
for `--upload-youtube`/`--force-youtube-upload`) - all using the offline
`sample` providers, synthetic in-test providers, or mocked HTTP/subprocess/
YouTube-client calls, so `pytest` never makes a real network call, shells
out to a real `ffmpeg` process, or talks to the real YouTube API.

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
  **This never touches YouTube** - `git.auto_commit`/`git.auto_push` and
  `youtube.enabled` are completely independent toggles.
- Scheduling wiring (cron/Task Scheduler/GitHub Actions examples above).

**Phase 3 (implemented, disabled by default - flip a config flag to try):**

- `youtube.enabled: true` - publishes `video.mp4` to YouTube via the
  official YouTube Data API v3, applying the canonical title (`title.txt`),
  description, category, and configured privacy status, then the generated
  thumbnail (`wta_daily/youtube/uploader.py`). Duplicate-upload-safe by
  default (`data/youtube-uploads.json`); `--upload-youtube`/
  `--force-youtube-upload` let you test or retry publishing on its own,
  without re-running data collection/narration/video assembly. See
  ["YouTube publishing"](#youtube-publishing) above for full setup.

**Future modules** (each addable independently, per the plugin architecture
above): ATP version, Top 25, tournament previews, head-to-head stats, player
biographies, career milestones, injury reports, weather, historical ranking
charts, multi-language narration (Spanish, French, ...), and a genuinely
new **projected/live ranking** feature - `rankings.projected_rankings_enabled`
is reserved for this but currently rejects being turned on (see ["Official
ranking vs. daily match activity"](#official-ranking-vs-daily-match-activity)
above) since it would need real logic to estimate provisional
in-tournament points, which the current data layer doesn't provide; if
built, it must always be clearly labeled ("projected No. 4") and never
presented as the official WTA ranking.
