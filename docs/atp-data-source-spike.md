# ATP Data-Source Spike

**Status:** research only. No ATP provider implementation, no production-behavior change, no points-table file, no persistence or narration edits.

**Research date:** 22 August 2026.

**Question:** Can we obtain ATP rankings, match results, tournament/round information, and enough tournament-state data to produce an ATP version of the current WTA daily video with comparable quality and reliability?

**Short answer:** Yes for a worthwhile ATP v1 (official-looking rankings with points, plus yesterday's completed singles matches). No for a free official ATP JSON backend equivalent to `api.wtatennis.com`, and no for first-class draw/bracket parity out of the box. Tournament elimination, champion, and previous-year lines can be reconstructed later from fixture lists, but that is additional work, not a documented draw API.

This document is the Stage 4 follow-up to [`docs/atp-support-audit.md`](atp-support-audit.md). It does not change `PlayerRanking`, `MatchResult`, or `TournamentRunStatus`.

---

## Evidence legend

Claims are tagged:

- **Documented** — current vendor or ATP documentation retrieved for this spike.
- **Observed** — HTTP response seen during this spike.
- **Repo-observed** — earlier live WTA testing recorded in this repository (README / provider docstrings). Not re-run against ATP in this spike.
- **Unknown** — not verified; do not treat as a fact.

This environment had no `APITENNIS_KEY` or `LIVETENNISAPI_KEY`, so paid ATP payloads were not fetched live. Official `api-tennis.com` / LiveTennisAPI ATP field claims below are therefore documented (and, where noted, illustrated by the vendor's own 2026 examples), not re-observed against a live key.

---

## 1. Executive Recommendation

**Preferred ATP data strategy:** use **api-tennis.com as a single provider** for ATP rankings and yesterday's completed matches. Implement it as **new plugins**, leaving the existing WTA-hardcoded `api_tennis` provider untouched. Ship ATP v1 as rankings + yesterday's matches. Reconstruct tournament-run status later from that same vendor's fixture list, not from the official ATP website.

Why this is the best practical option for this project:

1. Vendor docs currently state `get_standings` `event_type` is `'ATP'` or `'WTA'`. Changing the string is therefore a documented parameter, not a guess. It is still **not** sufficient to flip the existing WTA match provider in place: that module hard-codes WTA standings for identity, and ATP needs its own rankings plugin plus a day-first match path.
2. The same numeric `player_key` is used in standings and fixtures. That is the identity property this pipeline needs.
3. Rankings include **points**, not just place.
4. `get_fixtures` accepts `date_start` / `date_stop`, `player_key`, `tournament_key`, `tournament_season`, and `timezone`. That is enough to ask "who in the Top 10 finished a singles match on the reporting day."
5. The HTTP client already exists. Operational shape (query `method=`, `APIkey=`) is known.
6. A static ATP points YAML can be built from the official 2026 ATP rankings FAQ / rulebook, the same way WTA uses `data/wta_points_table.yaml`.

What this is not:

- It is not a WTA-equivalent official feed. There is **no** hobby-usable `api.atptour.com`.
- It does not give a first-class draw/bracket. Elimination/champion/previous-year narration will be absent in v1, then inferred from fixtures later.
- It does not give an official ranking-list publication date. Movement against our stored snapshot still works; "new official list vs same list fetched again" will be weaker than WTA's `rankedAt`.
- Vendor terms are "as is," with no broadcast/YouTube clearance. That is the same gray area already accepted for the WTA aggregators.

**If none of the sources were good enough, this document would say so.** They are good enough for a partial ATP v1. They are not good enough for silent full-parity with the current WTA elimination video.

LiveTennisAPI is the strongest **fallback / later `best_of` companion**, not the first rankings source: ATP coverage is documented, UTC timestamps are better, but the full ranking table is a PRO upsell, listing rows may omit `player_id`, and this repo already recorded a multi-month WTA coverage hole.

Do not scrape `atptour.com` or the Infosys ATP platform. Those paths are Cloudflare-blocked, `robots.txt`-restricted, and/or encrypted unofficial backends.

---

## 2. Required Data Matrix

Status values: **Yes** / **Partial** / **No** / **Unknown**.

| Requirement | api-tennis.com | LiveTennisAPI | Official ATP web/backend | BALLDONTLIE ATP | tennis-api.com (RapidAPI) |
| --- | --- | --- | --- | --- | --- |
| Rankings (Top 10 list) | Yes | Yes (PRO listing; per-player rank on FREE player objects is not a published table) | No (no usable public JSON API) | Yes (FREE tier) | Yes |
| Ranking points | Yes | Yes | No | Yes | Yes |
| Official ranking/list date | No (not in documented standings row) | Partial (`effective_date` on PRO listing) | No | Yes (`ranking_date`) | Partial (`updated` on example payload) |
| Stable player ID | Yes (`player_key`, shared with fixtures) | Partial (same ID space when rostered; listing may have `player_id: null`) | Unknown | Yes (same `player.id` on rankings and matches) | Partial (numeric core IDs and slug/name-style IDs coexist) |
| Yesterday's completed matches | Yes (date window on `get_fixtures`) | Yes (`/history/matches?from=&to=`, BASIC) | No | Partial (no date query param; filter `scheduled_time` client-side) | Yes (date / date-range fixtures) |
| Opponent | Yes | Yes | No | Yes | Yes |
| Score | Yes (`scores[]`) | Yes (`score.games`) | No | Yes | Yes |
| Round | Partial (present when `tournament_round` is populated; vendor examples sometimes empty) | Yes (`round` + `round_code`) | No | Yes | Yes |
| Tournament | Yes (`tournament_name` / `tournament_key`) | Yes (`tournament` / `tournament_id`) | No | Yes | Yes |
| Tournament timezone / date | Partial (optional IANA `timezone`; default documented as Europe/Berlin) | Yes (UTC ISO-8601 `scheduled_time`) | No | Partial (`scheduled_time` present; no timezone filter) | Unknown |
| Draw / bracket feed | No | No | No | No | Yes (documented draw endpoints; not live-tested) |
| Elimination | Partial (infer from fixture list) | Partial (infer from completed + upcoming) | No | Partial (infer from match list) | Partial / Yes if draw payload is complete (**Unknown** until tested) |
| Champion | Partial (infer final winner) | Partial | No | Partial | Partial / Yes if draw payload is complete (**Unknown**) |
| Previous-year lookup | Partial (`tournament_season` + same `tournament_key`) | Partial (history from 2023; archive 1968–2022 uses a different id space) | No | Partial (`season` on tournaments/matches) | Partial (year in draw/results paths) |

Notes:

- "Infer" means application logic over a match list, not a vendor draw object. That is how WTA `tournament_status.py` already works against `api.wtatennis.com` fixtures. It is extra work and weaker than a true bracket.
- Official ATP is **No** across the board for production use, not because rankings do not exist on the website, but because no stable, terms-safe, unattended JSON API was found.

---

## 3. api-tennis.com Findings

**Docs retrieved:** [API Tennis documentation](https://api-tennis.com/documentation) (v2.9.4), [MCP documentation](https://api-tennis.com/mcp-documentation), [pricing page](https://api-tennis.com/), [terms](https://api-tennis.com/terms-of-use).

**Live call this spike:** `GET https://api.api-tennis.com/tennis/?method=get_standings&event_type=ATP` without a key returned HTTP 200 and:

```json
{"error":"1","result":[{"param":"APIkey","msg":"The field is mandatory","cod":1005},{"param":"APIkey","msg":"Wrong login credentials","cod":1004}]}
```

That confirms the endpoint exists and accepts `event_type=ATP` as a query parameter. It does **not** prove the ATP payload shape. **Observed:** auth error only.

### 3.1 ATP standings are supported

**Documented.** `get_standings` parameter `event_type` is `'ATP'` or `'WTA'`. The PHP sample on the same page sets `$event_type = 'ATP'`.

This is the exact parameter. It is **not** `event_type_type`, and it is **not** the fixtures `event_type_key`. Those are different vocabularies:

| API surface | ATP singles value | Meaning |
| --- | --- | --- |
| `get_standings` `event_type` | `ATP` | Tour ranking table |
| `get_events` / fixtures `event_type_type` | `Atp Singles` | Match category |
| `get_events` `event_type_key` | `265` | Numeric category for Atp Singles (**documented example**) |

Do not assume `event_type="ATP"` on fixtures. Filter completed Top 10 singles with `event_type_key=265` or by `event_type_type` containing `Atp Singles` / `Singles`, the way the existing WTA provider already requires `"Singles"` in `event_type_type`.

### 3.2 Rankings fields

Documented WTA example row (REST):

```text
place, player, player_key, league, movement, country, points
```

Vendor MCP example for ATP, dated in their docs as a current-style response (**documented vendor example, not fetched here**):

```json
{ "rank": 1, "player": "Jannik Sinner", "player_id": 2072, "tour": "ATP", "movement": "same", "country": "Italy", "points": "13450" }
```

The MCP wrapper is a subset of the REST payload (they say so explicitly). REST uses `place` / `player_key` / `league`; MCP uses `rank` / `player_id` / `tour`. An ATP rankings plugin must parse the **REST** names.

**Missing vs `PlayerRanking`:**

| Model field | api-tennis standings | Gap |
| --- | --- | --- |
| `rank` | `place` | Maps cleanly |
| `player_id` | `player_key` | Maps cleanly; store as string |
| `name` | `player` | Maps cleanly; names are full (`Jannik Sinner` in MCP example), while some match fields use abbreviated `J. Sinner` |
| `country_code` | `country` is a name (`Italy`) | Need a country-name → ISO map, or leave `""` |
| `points` | `points` (string in examples) | Cast to int |
| `previous_rank` | `movement` is `up`/`down`/`same`, not a rank number | Leave `None`; our snapshot store supplies movement |
| `ranking_date` | not documented | Leave `None` |

### 3.3 Player IDs

**Documented:** standings `player_key`, fixtures `first_player_key` / `second_player_key`, H2H `player_key`, player profile `player_key`. MCP H2H example uses Sinner `2072` in both standings and a 2026 Wimbledon final vs Zverev `1980`.

Identity across rankings and matches looks shared. Accented-name matching is still a risk if a later plugin joins another vendor, but **not** required inside a single api-tennis ATP path if rankings `player_key` is reused for fixtures.

The existing WTA `api_tennis` provider currently resolves identity by **lowercased standings name**, not by the WTA official `player_id`. An ATP implementation should pass `player_key` through as `PlayerRanking.player_id` and query fixtures by that key, so ATP never depends on name matching.

### 3.4 Fixtures / results

`get_fixtures` supports:

- `date_start` / `date_stop` (`YYYY-MM-DD`)
- `event_type_key`, `tournament_key`, `tournament_season`, `match_key`, `player_key`
- `timezone` (IANA; **documented default `Europe/Berlin`**)

Completed matches: `event_status` in `{Finished, Retired}` (repo convention from WTA testing). Winner: `event_winner` = `First Player` / `Second Player`. Score: `scores[].score_first` / `score_second`.

MCP `get_tennis_fixtures` documents a **15-day** max window when dates are used, and says `tournament_id` alone returns the whole tournament. REST docs do not state that 15-day cap. Treat the 15-day limit as **Unknown** for REST until a key is used.

### 3.5 Rounds, tournaments, dates

- `tournament_round` is sometimes a useful string (`ATP Wimbledon - Final`, `… - Quarter-finals`) and sometimes `""` in vendor examples. Round quality is **Partial**.
- `tournament_key` + `tournament_name` + `tournament_season` are present.
- `event_date` + `event_time` are present. Default timezone Europe/Berlin is the most likely cause of the **repo-observed** WTA one-calendar-day drift. For ATP, pass an explicit `timezone` matching `reporting_day` (for example the Pi's configured zone) and still treat dates as less authoritative than LiveTennisAPI's UTC stamps.
- No surface on the fixture examples used by the current provider (`surface=None` today).

### 3.6 Draw / bracket

**No** dedicated draw method in the REST catalog (`get_events`, `get_tournaments`, `get_fixtures`, `get_livescore`, `get_H2H`, `get_standings`, `get_players`, odds, news). Tournament state would be inferred from a full fixture list for `tournament_key` + `tournament_season`, the same idea as WTA `determine_tournament_run_status`.

### 3.7 Pricing / quota for one daily Top 10 video

**Documented** monthly plans (August 2026 homepage):

| Plan | Price | Requests / day | Notes |
| --- | --- | --- | --- |
| Starter | $40 | 8,000 | Standings, fixtures, players, H2H, odds |
| Premium | $60 | 80,000 | Same methods |
| Business | $80 | 200,000 | Adds in-play odds + websockets |
| Ultra | $120 | 2,000,000 | Adds AI news + MCP |

14-day trial, no card required (homepage).

Likely ATP v1 call pattern (once each morning):

1. `get_standings&event_type=ATP` — 1 call
2. `get_fixtures` for yesterday (and maybe today, for reporting-day cutoff) with `event_type_key=265` — 1–2 calls
3. Optional later: per-tournament fixture pulls for Top 10 events still running — typically a handful

**Budget: well under 20 requests/run, ~600/month.** Starter's 8,000/day is two orders of magnitude more than needed. The constraint is **price**, not quota. $40/month is the cheapest self-serve plan that includes standings. There is no documented cheaper standings-only SKU.

If the project already has a trial/paid key for WTA evaluation, the same key should serve ATP; coverage is plan-gated by method, not by tour.

### 3.8 Terms

[Terms of use](https://api-tennis.com/terms-of-use): individual accounts, data "as is," no quality/uptime guarantee, logos/images remain copyrighted by owners, they accept no responsibility for how the feed is used. No clause grants YouTube/broadcast rights. Same gray area already documented in the README for aggregators.

### 3.9 Existing repo provider

`wta_daily/plugins/matches/api_tennis.py` **must stay WTA-only** until a later PR. It hard-codes `get_standings(event_type="WTA")` and is listed in `WTA_ONLY_PROVIDER_NAMES`. This spike does not change that.

---

## 4. LiveTennisAPI Findings

**Docs retrieved:** [plain-HTML reference](https://docs.livetennisapi.com/reference.html), [OpenAPI spec](https://github.com/livetennisapi/openapi/blob/main/openapi.yaml) (more complete than the HTML page), [Python client README](https://github.com/livetennisapi/livetennisapi-python), [pricing](https://livetennisapi.com/), [terms](https://livetennisapi.com/terms).

**Observed this spike:** `GET https://api.livetennisapi.com/api/public/v1/health` → `{"status":"ok","version":"v1"}`.

The HTML reference is **stale relative to OpenAPI**. It omits `/rankings` and `/tournaments`. Trust OpenAPI + the official client README for ATP rankings.

### 4.1 ATP coverage

**Documented:** "Coverage is every tour equally: ATP, WTA, Challenger, ITF and the junior Grand Slam draws." `tour=atp` is a first-class filter on matches, fixtures, history, and tournaments. An unrecognized tour is HTTP 400, not a silent pass-through.

### 4.2 Rankings

`GET /rankings`:

- **PRO:** full published table, `system=atp`, optional `as_of`, rows have `rank`, `points`, `previous_rank`, `effective_date`, `player_name`.
- **ULTRA:** per-player as-of records.
- **FREE player object** (`GET /players/{id}`): `ranking`, `ranking_points`, `ranking_movement`. Useful as a hint, **not** a Top 10 publication.

OpenAPI warning: listing rows may set `player_id` null "for players outside our roster" so the table has no silent holes. That is a real identity defect for joining matches.

`effective_date` is the publication week. That maps to `PlayerRanking.ranking_date` better than api-tennis.

### 4.3 Matches / yesterday

`GET /history/matches` (BASIC, $9.99/mo):

- `from` / `to` as `YYYY-MM-DD` or ISO-8601 UTC
- `tour=atp`, `draw=singles`, `player=`
- `scheduled_time` UTC
- `winner` 1|2, `score.games`, `round` / `round_code`, `tournament` / `tournament_id`, `event_status`

This is a clean day-first source **if** the match is in their corpus. **Repo-observed (WTA, August 2026):** 9/10 Top 10 dates matched `wta_official`; one player's history stopped four months early and silently omitted a Wimbledon final. No error is raised for a hole. ATP quality is **Unknown**; do not inherit the WTA 9/10 result as an ATP SLA.

The in-repo client only calls `/players` and `/history/matches?player=`. It has no `tour` filter. For ATP, name search without a tour constraint is riskier (more namesakes). OpenAPI player search does not document a `tour` query param.

### 4.4 Tournaments, rounds, draw

- `GET /tournaments` (FREE): stable `id` across seasons, optional `category` (`masters_1000`, `atp_500`, …) **only when catalogues agree**; otherwise null.
- Rounds: controlled `round_code` (`F`, `SF`, `QF`, `R16`, …) — maps well to `wta_daily.rounds`.
- **No draw/bracket endpoint.** `draw=singles|doubles` is a filter, not a bracket.
- Upcoming fixtures (FREE) are name-only until players resolve to ids.

Elimination/champion can be inferred if you collect a player's completed matches plus unfinished fixtures in the same `tournament_id`. That is more paging than api-tennis's `tournament_key` dump, because history listing is not documented as "all matches in one tournament in one call."

### 4.5 Previous year

- `/history/matches`: January 2023 → now.
- `/history/archive/matches`: 1968–2022, **different id space** (`archive_player`). OpenAPI says archive `event_date` is tournament **start** date, not match date.
- Previous-year Wimbledon 2025 would use the modern history surface. Previous-year for a 2024 event might require the archive. Treat deep history as **Partial** and a different identity model.

### 4.6 Pricing / quota

| Plan | Price | Adds | Limit |
| --- | --- | --- | --- |
| FREE | $0 | live/upcoming, players, fixtures, tournaments | 30/min · 1,000/day |
| BASIC | $9.99 | completed history + tape | 60/min · 10,000/day |
| PRO | $29.99 | ranking listing, events, markets, bulk | 300/min · 100,000/day |
| ULTRA | $99.99 | model, websocket, as-of player rankings | 600/min · 500,000/day |

ATP v1 that needs **both** a published ranking table and yesterday's results needs **PRO** ($29.99), not BASIC. BASIC alone cannot list the ATP Top 10.

Call pattern on PRO: 1× `/rankings?system=atp&limit=10` + 1× `/history/matches?tour=atp&draw=singles&from=…&to=…` ≈ 2 calls/day. Quota is not the issue.

### 4.7 Terms

[Terms](https://livetennisapi.com/terms): license to use responses in your own applications; no reselling the raw feed; no scraping/caching beyond what is reasonably necessary; no implying endorsement; data "as is"; best-effort single-region service. Narrating scores in a YouTube video is not forbidden in the text retrieved; redistributing a competing feed is. Still not an official ATP license.

### 4.8 Reliability judgment

Strengths: UTC dates, `tour=atp`, round codes, ranking `effective_date`, already integrated.

Weaknesses: PRO required for rankings; possible null ranking `player_id`; documented/observed WTA coverage holes; HTML docs lag OpenAPI; no draw; name search without tour filter.

**Not the preferred sole ATP source for v1.** Keep it as the first `best_of` companion after an ATP api-tennis provider exists, using LiveTennisAPI's own ids only if rankings also come from LiveTennisAPI, or accepting name reconciliation (see §7).

---

## 5. Official ATP / Public Backend Findings

### 5.1 There is no WTA-style public JSON API

**Observed this spike:**

| URL | Result |
| --- | --- |
| `https://api.atptour.com/` | DNS failure (host does not resolve) |
| `https://www.atptour.com/en/rankings/singles` | HTTP 403 Cloudflare |
| `https://www.atptour.com/-/ajax/Rankings/GetRanking` | HTTP 403 Cloudflare |
| `https://www.atptour.com/en/-/www/rankings/singles` | HTTP 403 Cloudflare |
| `https://www.atptour.com/en/-/www/scores/current` | HTTP 403 Cloudflare |
| `https://edx.atptour.com/en/rankings/singles` | HTTP 200 **HTML** (~600 KB), not a rankings JSON API |
| `https://edx.atptour.com/en/-/www/rankings/singles` | HTTP 302 to site 404 |
| `https://itp-atp-sls.infosys-platforms.com/` and common API paths | HTTP 403 CloudFront/S3 |
| `https://api.wtatennis.com/tennis/players/ranked?type=rankSingles&metric=singles&pageSize=1` | HTTP 200 JSON — contrast: WTA backend still open |

**Observed WTA sample (22 Aug 2026):** Aryna Sabalenka rank 1, 8670 points, `rankedAt=2026-08-10T00:00:00Z`. That is the quality bar ATP does not currently match with a public official API.

### 5.2 robots.txt

`https://www.atptour.com/robots.txt` **observed** `200`. Among other rules:

```text
User-Agent: *
Disallow: /sitecore/
Disallow: */ajax/*
Disallow: /*/scores/archive/*
Disallow: /*/scores/match-stats
```

`Allow: /` for ordinary pages does not make the unofficial `/-/www/` or `/-/ajax/` JSON paths a supported API. Those ajax paths are explicitly disallowed.

### 5.3 Infosys / "hidden JSON" history

The ATP site's CSP and third-party writeups point at `itp-atp-sls.infosys-platforms.com`. Historical Stack Overflow discussion describes **AES-encrypted** responses keyed off `lastModified` — a private website backend, not a developer API. This spike received 403s and did not decrypt anything.

**Do not recommend this.** It is undocumented, bot-walled, encrypted, and would need constant babysitting. That is the opposite of an unattended Pi job.

### 5.4 Official commercial rights

Sportradar publishes an [Official ATP Addendum](https://sportradar.com/official-atp-addendum/) stating official ATP data is licensed via Tennis Data Innovations (TDI). Production pricing is sales-quoted; a 30-day / 1,000-request trial exists for some Sportradar REST products. Third-party cost chatter ("from $1,250/mo") remains unverified. **Enterprise comparison only.** Not a hobby v1 path.

### 5.5 Official points documentation (usable as a table, not as a feed)

The rankings FAQ is readable on `edx.atptour.com` (HTML). It publishes the 2026 singles points breakdown used in §8. The FAQ itself says the ATP Rulebook controls if they disagree.

**Verdict:** official ATP web/backends are **not suitable for production use** in this application.

---

## 6. Other Providers

Only candidates a small personal project could actually buy.

### 6.1 BALLDONTLIE ATP — serious cheap alternative

**Docs:** [atp.balldontlie.io](https://atp.balldontlie.io/), [OpenAPI](https://www.balldontlie.io/openapi/atp.yml), [terms](https://balldontlie.io/terms.html).

ATP-only (men's singles). Same `player.id` on rankings and matches in documented examples. Rankings (FREE) include `rank`, `points`, `movement`, `ranking_date`. Tournaments include `category`, `draw_size`, `season`, `start_date` / `end_date`. Matches (ALL-STAR, $9.99/mo) include opponent, winner, score, `set_scores`, `round`, `scheduled_time`, `match_status`.

Gaps:

- Matches have **no `date=` query**. Yesterday requires paging by `player_ids` / `tournament_ids` / `season` and filtering `scheduled_time`. Workable for Top 10, clumsier than api-tennis or LiveTennisAPI.
- No draw endpoint.
- Free tier is 5 req/min. ALL-STAR is 60/min.
- **Observed:** unauthenticated rankings/players → HTTP 401 `Unauthorized`. No live quality check.
- Documented ranking examples look internally inconsistent with "current" tennis (placeholder-ish dates such as `2026-12-01` in the docs). Treat examples as illustrations only.
- Another new vendor and ID space.

Terms (retrieved 22 Aug 2026) are unusually permissive for media/publishing, with restrictions on competing with them and on selling unmodified raw data. Still not official ATP.

**Use as a comparison / backup if api-tennis pricing or date drift becomes the blocker.** Not preferred over a vendor already in-tree.

### 6.2 tennis-api.com / RapidAPI "Tennis API – ATP WTA ITF"

**Docs:** [docs.tennis-api.com](https://docs.tennis-api.com/), [tournaments/draws](https://tennisapidoc.matchstat.com/tournaments), [pricing](https://tennis-api.com/api-pricing/).

This is the only hobby-priced source found that **documents a real draw endpoint**:

```text
GET /tennis/v2/tournament/{tour_type}/{tournament}/{year}/draws
```

Example: ATP Gstaad 2026. Also documents date fixtures, ATP/WTA rankings with points, and `updated` timestamps.

Why it is not the v1 recommendation:

- New vendor, RapidAPI key/host coupling, product-split confusion (five hosts).
- Draw path is keyed by **URL-encoded tournament name**, not a stable numeric id. That is fragile for automation.
- Core vs "MS" APIs mix numeric ids and name slugs (`sinner-jannik`).
- Quality and freshness **Unknown** (no key).
- This repo already rejected "GoalServe / RapidAPI tennis aggregators" as optional fallbacks, not defaults.

**Revisit only if tournament-status parity becomes the next priority after ATP v1 is in production** and api-tennis fixture inference proves too weak.

### 6.3 Sportradar Tennis API

Official ATP partner. Self-serve trial is real; production is sales. Out of scope for v1. Useful only as the "if we ever need licensed official data" escape hatch behind the existing plugin interfaces.

### 6.4 Jeff Sackmann / Tennis Abstract `tennis_atp`

Excellent historical CSVs, not a same-day API. Licensed **CC BY-NC-SA 4.0**. Already rejected in the README for a potentially monetized YouTube pipeline. Unchanged.

### 6.5 SportsDataIO / Sportmonks / UTR

Unchanged from the README: tennis is enterprise or the wrong ranking system. Not re-opened.

---

## 7. Identity / Model Mapping

Preferred source: **api-tennis.com REST**, new ATP plugins, `player_id = str(player_key)`.

### 7.1 `PlayerRanking`

| Field | Source | Notes |
| --- | --- | --- |
| `rank` | `place` | int |
| `player_id` | `player_key` | opaque string; **do not** reuse WTA official ids |
| `name` | `player` | prefer standings spelling |
| `country_code` | derive from `country` or `""` | model allows empty |
| `points` | `points` | int; essential; present |
| `previous_rank` | omit | movement comes from `RankingsSnapshotStore` |
| `ranking_date` | omit | **model gap vs WTA official**; pipeline already allows `None` |

No model change required. The feature gap is operational (no list date), not structural.

### 7.2 `MatchResult`

| Field | Source | Notes |
| --- | --- | --- |
| `opponent` | other player's name | fixtures also have abbreviated names |
| `tournament` | `tournament_name` | naming will not match WTA catalogue strings; ATP-only is fine |
| `round` | parse `tournament_round` with the existing suffix map | `None` if empty/unrecognized |
| `score` | `scores[]` | same tiebreak quirk already documented (`6.3`) |
| `won` | `event_winner` vs our slot | skip if missing |
| `match_date` | `event_date` after explicit timezone | never substitute tournament start |
| `surface` | usually absent | `None` |

Day-first: one (or two) `get_fixtures` calls for the reporting-day window, keep `Atp Singles` rows whose `first_player_key` / `second_player_key` is in the Top 10 id set. That fills `MatchLookupResult.matches` without per-player name search.

### 7.3 `TournamentRunStatus`

**v1: leave unset** (same as today's `api_tennis` / `live_tennis_api` WTA path). Downstream already treats missing status as `UNKNOWN`.

**Later inference from fixtures** (no model change):

- Unfinished fixture involving the player → `ACTIVE`
- Latest finished loss → `ELIMINATED`, `eliminated_by` = opponent
- Win in `Final` → `CHAMPION`
- No fixtures → `DID_NOT_PARTICIPATE`
- `tournament_group_id` ← `tournament_key` (stable enough for YoY if the vendor keeps keys)
- `category` ← **not provided**; must come from a local ATP tournament-category map or a later catalogue join
- `points_earned` ← local `data/atp_points_table.yaml` (not in this spike)
- Previous year ← `get_fixtures` with `tournament_key` + `tournament_season=year-1`

Model gaps vs WTA official: no draw size, no official category, no `MatchTimeStamp` timezone object. Those are provider problems, not reasons to change the dataclass.

### 7.4 Combining two providers

If rankings come from api-tennis and matches from LiveTennisAPI or BALLDONTLIE, **IDs will not match**. Reconciliation would be name-based (exactly the fragility this project already knows). Prefer one ID space for v1.

If a later `best_of` adds LiveTennisAPI ATP matches, resolve LiveTennisAPI ids from **api-tennis names** with the existing conservative picker, and never write those ids into `PlayerRanking.player_id`.

---

## 8. ATP Ranking and Tournament Points

### 8.1 Ranking points (the Top 10 number)

ATP singles rankings are a 52-week best-results system (18 counting events; Finals can be a 19th). A rankings provider must copy the **published** points total, not recompute it from daily results. That matches the current architecture.

api-tennis and LiveTennisAPI both document a points field on ATP rankings. BALLDONTLIE does too. A rank-only source would be materially weaker; none of the serious candidates are rank-only.

Without `ranking_date`, `compute_movement(..., same_official_ranking_list=)` cannot detect "same official list, new calendar day" as cleanly as WTA. Movement by stored snapshot still works.

### 8.2 Tournament-round points (static YAML)

ATP points **are** standardized enough for a `data/atp_points_table.yaml` analogous to the WTA file. Source: [ATP rankings FAQ](https://edx.atptour.com/en/rankings/rankings-faq) (HTML retrieved 22 Aug 2026) and the 2026 rulebook chapter on PIF ATP Rankings.

2026 singles main-draw points (FAQ table):

| Category | W | F | SF | QF | R16 | R32 | R64 / R128 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Grand Slams | 2000 | 1300 | 800 | 400 | 200 | 100 | 50 / 10 |
| ATP 1000 (96) | 1000 | 650 | 400 | 200 | 100 | 50 | 30 / 10 |
| ATP 1000 (56) | 1000 | 650 | 400 | 200 | 100 | 50 | 10 |
| ATP 500 (48) | 500 | 330 | 200 | 100 | 50 | 25 | — |
| ATP 500 (32) | 500 | 330 | 200 | 100 | 50 | — | — |
| ATP 250 (48) | 250 | 165 | 100 | 50 | 25 | 13 | — |
| ATP 250 (32) | 250 | 165 | 100 | 50 | 25 | — | — |

Complications to encode or omit (same philosophy as WTA: omit rather than guess):

| Complication | Handling |
| --- | --- |
| Nitto ATP Finals | Round-robin: 200 per RR win, 400 SF win, 500 final win; 1500 undefeated champion. **Omit or special-case**; do not pretend it is a normal knockout row. |
| United Cup | FAQ lists 500 for W only. Team event; **omit** unless a later PR defines a rule. |
| Byes | Rulebook: a bye then a first-round loss earns first-round loser points, not "round reached" points. Need the same honesty as WTA. |
| Qualifying | Separate Q / Q3 / Q2 table in the FAQ. Only needed if ATP v2 narrates qualifying. |
| Draw-size variants | 96 vs 56 Masters; 48 vs 32 for 500/250; also 16/24-draw rows in the rulebook PDF. Key the YAML by category + draw size, like WTA. |
| Monte Carlo | Masters 1000 but "Best Other" for the 18-event formula. Points table still uses the 1000 schedule; the 18-event rule does not change per-round awards. |
| Olympics | Confirm against the current rulebook before adding; likely omit. |
| Challenger / ITF | Not needed for Top 10 daily videos. |

**Do not implement the YAML in this spike.** When it is added, it must be a new file, never a prefix on `data/wta_points_table.yaml`.

---

## 9. Feature-Parity Assessment

Classification is against **the proposed ATP v1 source (api-tennis.com, rankings + yesterday matches, no fixture-inferred status yet).**

| Current WTA feature | ATP v1 with proposed source |
| --- | --- |
| Official Top N list with points | **Available immediately** |
| Stable player id for snapshots / featured player | **Available immediately** (`player_key`) |
| Movement vs previous snapshot | **Available immediately** (store-based; no vendor previous-rank required) |
| "New official ranking list" vs same list re-fetched | **Unavailable** without `ranking_date` (degrades to rank-number comparison, already supported) |
| Yesterday completed singles match (opponent, score, tournament) | **Available immediately** |
| Round label on that match | **Available with additional work** (normalize `tournament_round`; omit when empty) |
| Reporting-day timezone / late-night cutoff | **Available with additional work** (pass explicit `timezone`; keep existing `reporting_day.py`; expect residual Berlin-default drift if omitted) |
| Surface on match cards | **Unavailable** from fixtures as documented |
| Day-first "did not play" vs unresolved | **Available with additional work** (date-window scan + `event_type_key`) |
| Still alive / eliminated / champion | **Unavailable** in v1; **available with additional work** via fixture inference |
| Eliminated-by / round reached | **Unavailable** in v1; later inference |
| Tournament category + points earned | **Available with additional work** (local ATP points YAML + category map) |
| Previous-year same tournament | **Available with additional work** (`tournament_season`) |
| `best_of` second source | **Available with additional work** (LiveTennisAPI `tour=atp`; name reconciliation) |
| TourProfile branding / pronouns | **Already available** (presentation PR); not a data-source item |
| Featured player | **Available immediately** as config pointing at an ATP `player_key`; disable until then |
| Persistence isolation / output dirs | **Not a data-source item**; still required before a same-Pi dual run ([audit](atp-support-audit.md) §6) |
| Official ATP attribution URL | **Unavailable** — do not invent `api.atptour.com` |

---

## 10. Cost and Operational Risk

### 10.1 Once-daily Top 10 budget

Assume one ATP job every morning, Top 10, no live polling.

| Source | Plan needed for rankings+yesterday | Monthly | Calls / run | Headroom |
| --- | --- | --- | --- | --- |
| api-tennis.com | Starter | **$40** | ~2–20 | 8,000/day |
| LiveTennisAPI | PRO | **$29.99** | ~2–15 | 100,000/day |
| LiveTennisAPI | BASIC | $9.99 | matches only | cannot list rankings |
| BALLDONTLIE | ALL-STAR | **$9.99** | rankings free; matches paid; more paging | 60/min |
| Official ATP JSON | — | $0 | — | **not usable** |
| Sportradar | sales | trial then custom | — | not hobby |

api-tennis is the most expensive of the hobby options that already sit in this repo. The extra ~$10 vs LiveTennisAPI PRO buys a single standings call that includes every `player_key`, which avoids PRO-listing null ids and avoids a new vendor. Quota is irrelevant; **dollar cost and date-timezone behavior** are the real knobs.

### 10.2 Operational risks (Pi, unattended)

| Risk | api-tennis | LiveTennisAPI | Official ATP | BALLDONTLIE |
| --- | --- | --- | --- | --- |
| Auth | query `APIkey` | Bearer | n/a | `Authorization` header |
| Historical yesterday | date window | `from`/`to` UTC | n/a | client-side filter |
| Missing data | no SLA; WTA coverage was good **repo-observed** | silent per-player holes **repo-observed** | n/a | **Unknown** |
| Tournament names | vendor strings | vendor strings | n/a | vendor strings |
| ID stability | numeric keys, look stable | numeric; listing holes | n/a | numeric |
| Endpoint stability | long-lived `method=` API | v1 additive; HTML docs drift | Cloudflare / Infosys | small third-party |
| Latency | fine for daily | fine | n/a | fine |
| Scraping required | no | no | **yes, and blocked** | no |
| Terms | as-is | as-is, no competing feed | ToS + ajax disallow | relatively permissive |
| Babysitting | low | medium (coverage + docs drift) | high | medium (new, unverified) |

Reliability ranking for this project's constraints: **api-tennis (known) > LiveTennisAPI (known gaps) > BALLDONTLIE (cheap, unverified) >> official ATP unofficial JSON (do not use).**

---

## 11. Recommendation for ATP v1

**Rankings + yesterday's matches first. Tournament-status parity later.**

No single hobby source already matches `wta_official`'s draw scan. Waiting for that before any ATP video would stall a product that can already say:

- who is in the ATP Top 10 and on how many points
- who moved versus last snapshot
- who won or lost yesterday, against whom, in which tournament, at which round (when the vendor populated it)

That is a worthwhile daily video. It will be thinner than today's WTA show on quiet days (no "he was eliminated by X in the quarterfinals, 100 points, worse than last year"). Those sentences should stay off until fixture inference (or a later draw vendor) is proven.

**Architecture choice:** Option A (one provider) for v1 — api-tennis.com. Option B (split providers) is rejected for v1 because of name reconciliation. Option C describes the **product** slice (partial narration), not a second vendor.

**Out of v1:** ATP points YAML can wait until status inference exists; without `category` + `round_reached` it has nothing to look up.

**Before any same-machine dual run:** use a separate `data_dir` / `output_dir` / YouTube token, as the audit already requires. That is operational, not a data-source finding.

---

## 12. Proposed Next PR

**One next implementation PR:**

> Add new ATP rankings and match plugins that call api-tennis.com with `event_type=ATP` / Atp Singles fixtures, map into the existing `PlayerRanking` / `MatchResult` models, and ship `config/config.atp.example.yaml` pointing at those plugins with a separate `data_dir` and `output_dir`. Do not modify the existing WTA `api_tennis` provider, WTA points table, persistence schema, narration, or scheduler.

Suggested scope for that PR (still not this one):

- `wta_daily/plugins/rankings/api_tennis_atp.py` (name TBD) — `get_standings(event_type="ATP")` → Top N `PlayerRanking`
- `wta_daily/plugins/matches/api_tennis_atp.py` — day-first `get_fixtures` for the reporting date; **do not** fill `tournament_status` yet
- Reuse `ApiTennisClient` if it can stay tour-agnostic; do not change the WTA match provider's `event_type="WTA"` call
- Offline fixtures from a captured or vendor-shaped sample
- Tests that ATP plugins are rejected from a WTA production-style `best_of` only if that is already required — default: keep WTA defaults unchanged
- No `data/atp_points_table.yaml` yet
- No LiveTennisAPI ATP work in that PR

Stop after that provider PR is designed/implemented in a later session. This spike ends here.

---

## Appendix A — Candidate architectures

### Option A — One provider for everything

**api-tennis.com** is strong enough for rankings + matches + later fixture-inferred status. It is **not** strong enough for a first-class draw. That is still the best A.

LiveTennisAPI PRO is a coherent A if the project would rather pay $30 than $40 and wants UTC + `effective_date`, at the cost of ranking `player_id` holes and known coverage gaps.

BALLDONTLIE ALL-STAR is a coherent cheap A if a trial proves yesterday filtering via `scheduled_time`.

### Option B — Split providers

Example: BALLDONTLIE FREE rankings + LiveTennisAPI BASIC matches.

Rejected for v1. Different ID spaces. Safe reconciliation would need a maintained mapping table, not live fuzzy names. Accented ATP names (Alcaraz, Šviontek-class issues on WTA already) make this worse, not better.

If Option B is ever used, the safe pattern is: rankings provider owns `player_id`; match provider keeps an internal alias map built from exact-name + country, and any ambiguous match is `unresolved`, never a guess.

### Option C — Partial ATP v1

This is the recommended **product** cut, implemented on Option A's api-tennis stack.

---

## Appendix B — Sources cited

- https://api-tennis.com/documentation
- https://api-tennis.com/mcp-documentation
- https://api-tennis.com/
- https://api-tennis.com/terms-of-use
- https://docs.livetennisapi.com/reference.html
- https://github.com/livetennisapi/openapi/blob/main/openapi.yaml
- https://github.com/livetennisapi/livetennisapi-python
- https://livetennisapi.com/
- https://livetennisapi.com/terms
- https://edx.atptour.com/en/rankings/rankings-faq
- https://www.atptour.com/robots.txt
- https://www.atptour.com/-/media/files/rulebook/2026/2026-rulebook-chapter-9_pif-atp-rankings_31mar26.pdf
- https://sportradar.com/official-atp-addendum/
- https://atp.balldontlie.io/
- https://www.balldontlie.io/openapi/atp.yml
- https://balldontlie.io/terms.html
- https://docs.tennis-api.com/
- https://tennisapidoc.matchstat.com/tournaments
- https://api.wtatennis.com/tennis/players/ranked (live contrast)
- Repository: `wta_daily/models.py`, `wta_daily/plugins/api_tennis_client.py`, `wta_daily/plugins/matches/api_tennis.py`, `wta_daily/plugins/live_tennis_api_client.py`, `docs/atp-support-audit.md`, README data-source section
