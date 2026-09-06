# ATP weekly tournament-activity investigation (BALLDONTLIE)

**Status:** research only. **No MatchProvider was implemented.** ATP v1 stays
rankings-only. WTA production is unchanged.

**Research date:** 24 August 2026 (UTC).

**Question:** Can the existing BALLDONTLIE ATP account (the same free key
already used for weekly rankings) supply enough match/tournament facts to
narrate what each Top 10 player did during the ranking week?

**Answer: No, not on the free tier.** The facts this feature needs live on
`GET /atp/v1/matches`, which BALLDONTLIE documents as **ALL-STAR (paid)**.
Tournaments on the free tier are calendar metadata only: they do not say
who played, who won, which round, or the score.

This document is a current-docs re-check of that gate. It does **not**
approve a paid upgrade, scraping, or a second vendor.

Sources (retrieved 24 August 2026):

- Official ATP API HTML: https://atp.balldontlie.io/
- OpenAPI: https://www.balldontlie.io/openapi/atp.yml
- Earlier $0 recommendation: [`atp-free-data-source-spike.md`](atp-free-data-source-spike.md)

This environment had **no** `BALLDONTLIE_API_KEY`. Authenticated payloads
were not fetched. Schema and tier claims below are **Documented**, not
live-probed.

---

## 1. Decision

Do **not** implement `plugins/matches/balldontlie_atp.py` until one of these
is explicitly approved:

1. **Paid BALLDONTLIE ALL-STAR** for ATP ($9.99/mo documented), using the
   existing `BALLDONTLIE_API_KEY` after the account is upgraded, **or**
2. A **different $0 source** that actually exposes completed singles
   results (none was validated in the earlier free-data spike).

Do **not**:

- scrape ATP.com
- call `/atp/v1/matches` on the free key and treat HTTP 401 as “did not compete”
- narrate “did not compete during this ranking week” from missing match data
- mix a second vendor’s matches onto BALLDONTLIE ranking IDs without an
  identity plan (see [`atp-data-source-spike.md`](atp-data-source-spike.md))

The pipeline already has a `MatchProvider` interface and `match_provider: none`
for ATP. That remains the correct production configuration.

---

## 2. Endpoint inventory (current OpenAPI + HTML docs)

| Endpoint | Free? | What it actually returns | Enough for this feature? |
| --- | --- | --- | --- |
| `GET /atp/v1/rankings` | **Yes** | Rank, points, `ranking_date`, `player.id` | Already used for ATP v1 |
| `GET /atp/v1/players` and `/players/{id}` | **Yes** | Profile only | Identity lookup only |
| `GET /atp/v1/tournaments` | **Yes** | Calendar metadata | **No** — no draw, no results |
| `GET /atp/v1/tournaments/{id}` | **Yes** | Same tournament object, optional `season` | **No** — still no results |
| `GET /atp/v1/matches` | **No (ALL-STAR)** | Singles matches | **Yes, if paid** |
| `GET /atp/v1/matches/{id}` | **No (ALL-STAR)** | One match | Same gate |
| `GET /atp/v1/atp_race` | **No (ALL-STAR)** | Race to Turin | Not this feature |
| `GET /atp/v1/match_stats` | **No (GOAT)** | Point-level stats | Not required |
| Head-to-head / career stats / odds | **No (GOAT)** | Unrelated | No |

Documented account table (https://atp.balldontlie.io/, 24 Aug 2026):

| Endpoint | Free | ALL-STAR | GOAT |
| --- | --- | --- | --- |
| Players | Yes | Yes | Yes |
| Tournaments | Yes | Yes | Yes |
| Rankings | Yes | Yes | Yes |
| **Matches** | **No** | **Yes** | Yes |
| ATP Race | No | Yes | Yes |
| Match Statistics | No | No | Yes |

Quota (documented): Free 5 req/min; ALL-STAR 60 req/min ($9.99/mo); GOAT
600 req/min ($39.99/mo). HTTP **401** means missing key **or** the account
tier does not include the endpoint.

Coverage note: the ATP API is **men's singles only**. That matches this
product. Doubles/Challenger/exhibitions are not in this feed.

---

## 3. What free tournaments give us (and what they do not)

`ATPTournament` (OpenAPI) fields:

- `id`, `name`, `location`, `surface`
- `category` (`Grand Slam`, `ATP 1000`, `ATP 500`, `ATP 250`)
- `season`, `start_date`, `end_date`
- `prize_money`, `prize_currency`, `draw_size`

List filters: `tournament_ids`, `season`, `surface`, `category`.
Pagination: `cursor`, `per_page` (max 100, default 25).

This is enough to *name events that existed during a ranking week*. It is
**not** enough to say:

- whether a given Top 10 player entered
- how far he advanced
- opponent / score / retirement / walkover
- champion vs finalist vs still playing

Inferring “he played Cincinnati” from “Cincinnati’s dates overlap the
ranking week” would be fiction.

---

## 4. What paid matches would give us (not used)

Documented so a later paid implementation does not have to rediscover it.
**None of this is available on the free key.**

### Identity

- Players are integers: `player.id` (same object as rankings).
- Matches embed `player1`, `player2`, nullable `winner` as `ATPPlayer`.
- Ranking `player.id` can join match participants **inside this vendor**.

### Querying matches

`GET /atp/v1/matches` documented query params:

| Param | Meaning |
| --- | --- |
| `player_ids[]` | Matches involving those player IDs |
| `tournament_ids` | Matches in those tournaments |
| `season` | Season year |
| `round` | String (`Finals`, `Semi-Finals`, …) |
| `is_live` | Live matches only |
| `cursor` / `per_page` | Cursor pagination, max 100 |

**There is no `date=` / `from=` / `to=` filter on matches.** A ranking-week
window would have to be applied client-side.

### Match date

HTML examples include `scheduled_time` (ISO datetime) and
`not_before_text`. The **OpenAPI `ATPMatch` schema does not list
`scheduled_time`**. A paid implementation must treat match date as
**Unknown** unless the live payload actually contains a parseable
`scheduled_time` (or equivalent). Do not invent dates from tournament
`start_date`.

### Result fields (OpenAPI)

- `round` — free-text (`Finals`, `Semi-Finals`, etc.)
- `winner` — player or null
- `score` — string (e.g. `6-3 6-4 7-5`) or null
- `set_scores` — structured games/tiebreaks
- `match_status` enum: `finished`, `in_progress`, `scheduled`,
  `suspended`, `walkover`, `retired`, `defaulted`
- `status_state` — normalized lifecycle (`scheduled`, `in_progress`,
  `final`, `postponed`, `canceled`, `delayed`, `suspended`, `abandoned`,
  `unknown`)
- `is_live`

**Not documented:** bye as a first-class match type. Do not invent a score
for walkover/retired/defaulted. A bye is not a played match.

### Efficient call pattern (if ALL-STAR were approved)

Prefer **tournament-first**, not ten independent career scans:

1. Free `GET /atp/v1/tournaments?season=YYYY` (and adjacent year if the
   week straddles 1 January).
2. Keep events whose `start_date`/`end_date` overlap
   `(previous_ranking_date, current_ranking_date]`.
3. One paged `GET /atp/v1/matches?tournament_ids[]=…` per overlapping
   event (or batched `tournament_ids` if the vendor accepts several).
4. Map completed singles rows onto the current Top 10 `player.id` set
   in memory. Cache tournament and match payloads **inside one pipeline
   run**.

`player_ids[]` for the ten ranked IDs is a backup if tournament listing
is empty; it still needs client-side date filtering and can pull older
matches outside the ranking week.

---

## 5. Reporting interval (how we would have defined it)

ATP v1 already stores official list dates:

- Current: `DailyReport.ranking_date` from BALLDONTLIE `ranking_date`
- Previous: `RankingsSnapshotStore.get_previous_snapshot()` → that
  snapshot’s `PlayerRanking.ranking_date` (same list date on every row)

**Decision, if matches existed:** the reporting interval is

```text
(previous official ranking_date, current official ranking_date]
```

using published list dates, not the job’s `report_date` and not “yesterday.”

If either ranking date is missing, do **not** guess a Monday. Treat
tournament activity as **unknown** (provider/interval failure), never as
confirmed inactivity.

A player’s most recent historical match is **not** a substitute for
“played during this interval.” That is the same class of bug
`MatchProvider.get_matches_for_date` exists to prevent.

---

## 6. What is missing for the requested narration

Required for “what did he do on court this week?” vs free-tier reality:

| Required fact | Free rankings | Free tournaments | Paid matches |
| --- | --- | --- | --- |
| Did he play a completed singles match in the interval? | No | No | Yes, if date field exists on payload |
| Tournament name | No | Name only, not “he played it” | Nested `tournament.name` |
| Round reached / champion / finalist | No | No | Infer from completed matches + `round` + `winner` |
| Still alive vs eliminated | No | No | Infer; do not call a SF winner a “semifinalist” if the final is not done |
| Opponent / score | No | No | `player1`/`player2`/`score` when `match_status=finished` |
| Walkover / retired / default | No | No | `match_status` enum |
| Bye | No | No | Not documented |
| Confirmed “did not compete” | No | No | Only after a successful match fetch that returns none in-interval |
| Unknown vs no activity | n/a | n/a | Failed/401/timeout → unknown, **not** “did not compete” |

Without paid matches, any weekly script that says “after winning
Cincinnati” or “he did not compete during this ranking week” would be
inventing court activity.

---

## 7. Failure isolation (unchanged)

If a paid match plugin is added later: rankings, snapshot movement, and
(when present) point deltas must survive match-fetch failures. Record the
error, omit tournament claims, still produce the rankings video. Do not
translate a 401/timeout into “did not compete.”

That is the same rule as WTA optional match sources. WTA daily “yesterday”
semantics stay WTA-only.

---

## 8. Configuration (not changed)

`config/config.atp.example.yaml` keeps:

```yaml
rankings_provider:
  provider: balldontlie_atp

match_provider:
  provider: none
```

Do not point `match_provider` at a BALLDONTLIE matches plugin that cannot
succeed on the free key.

---

## 9. Relationship to ranking-point deltas

Week-to-week official point change (previous snapshot points vs current
points) is a **list-to-list** delta. Even with match data, narration must
not say a Cincinnati semifinal “earned exactly N ranking points” unless a
separate authoritative points-earned calculation exists. ATP rankings are
a rolling 52-week window.

---

## 10. What to do next (needs a product decision)

1. **Stay rankings-only (current main).** Honest. $0. No tournament
   sentences.
2. **Approve BALLDONTLIE ALL-STAR** for ATP. Then implement
   `plugins/matches/balldontlie_atp.py` behind `MatchProvider`, using the
   interval and tournament-first fetch described above, after confirming
   live `scheduled_time` (or another date field) on real match payloads.
3. **Approve a different $0 match source.** Re-validate identity against
   BALLDONTLIE `player.id` before joining.

Until (2) or (3) is chosen, stop here.
