# ATP Support Architectural Audit

**Status:** audit only. No ATP implementation, no refactor, no production-behavior change.

This document inspects the current WTA daily video pipeline and describes what would be required to add ATP Top 10 support **without forking the application**. Existing WTA production behavior is the highest-priority constraint.

---

## 1. Executive Summary

**Assessment: moderate refactor required, with one significant external dependency.**

The application is closer to multi-tour than its `wta_daily` package name suggests, but farther than `tour: wta` in config implies.

What is already in good shape:

- The pipeline is genuinely plugin-based. Rankings, matches, script generation, graphics, voice, and video all sit behind small abstract interfaces. `DailyPipeline` talks to those interfaces, not to `api.wtatennis.com`.
- Internal models (`PlayerRanking`, `MatchResult`, `PlayerReport`, `DailyReport`, `TournamentRunStatus`) have **no gender field and no WTA-only data shape**. ATP players can occupy the same objects.
- `tour` is a real stored field on `DailyReport` and is already used to isolate ranking snapshots and YouTube upload records.
- Leaderboard and thumbnail headlines already render `{report.tour.upper()} TOP {n}`, so `tour: atp` would already print **ATP TOP 10** on those two graphics.
- README and plugin registry comments already describe ATP as "write new provider plugins," which is the right instinct.

What is not tour-agnostic yet:

- `tour:` does **not** select providers, points tables, narration language, titles, or pronouns. It is a storage/branding key, not a product switch.
- Narration, titles, and YouTube descriptions hard-code "WTA", "women's game", and she/her throughout.
- The production-grade match/tournament pipeline (`wta_official` day-first scan, draw-status, previous-year lookback, WTA points table, WTA round IDs) is deeply coupled to `api.wtatennis.com`. That is the mature, hard-won WTA implementation and should stay as a WTA provider, not be generalized in place.
- Several persistence paths are **not** tour-scoped. Flipping `tour: atp` in the same config on the same Pi would collide tournament-status history, the player cache, and the day's output folder.
- There is **no ATP rankings/match provider in the repo**, and the README's own data-source research does not identify a free official ATP JSON backend equivalent to `api.wtatennis.com`. That is the largest unknown.

The smallest sensible architecture is therefore: keep the shared pipeline and models; introduce a small **tour profile** at the config boundary; add ATP as new ranking/match plugins plus an ATP points table; isolate storage by tour. Do not rename the Python package, do not duplicate `DailyPipeline`, and do not sprinkle `if tour == "atp"` through narration and graphics.

After that work, `tour: atp` can drive branding, default providers, and storage namespace. It cannot be the *only* production setting: YouTube destination, featured player, and possibly paid API keys still need to differ.

---

## 2. Current Architecture

One CLI entry (`python -m wta_daily.cli`) loads `config/config.yaml` and runs `DailyPipeline`. The flow is:

```text
config.yaml
    |
    v
DailyPipeline.run()
    |
    +-- RankingsProvider.get_top_n()          # plugin (default: wta_official)
    +-- RankingsSnapshotStore (movement vs prior snapshot for this tour)
    +-- MatchProvider.get_matches_for_date()  # plugin (default: best_of)
    |       wta_official (day-first tournament scan + draw status)
    |       live_tennis_api (paid fallback, name-resolved)
    |       api_tennis (implemented, not default)
    +-- TournamentStatusStore (elimination/champion "new vs already told")
    +-- DailyReport (tour, ranking_date, players, featured_player, matches)
    |
    +-- ScriptGenerator.generate()            # template (default) or openai
    +-- generate_title() / generate_description()
    +-- GraphicsRenderer (leaderboard, player cards, featured card, thumbnail)
    +-- VoiceSynthesizer (ElevenLabs, optional)
    +-- VideoAssembler (ffmpeg, optional)
    +-- YouTube Data API v3 upload (optional, OAuth token = destination)
    +-- git commit of output + history (optional)
```

Persistent artifacts:

| Path | Role |
| --- | --- |
| `data/rankings-history.json` | Daily ranking snapshots, entries already include `tour` |
| `data/players.json` | `player_id -> {name, country_code}` cache, **no tour** |
| `data/tournament-status-history.json` | Last reported elimination/title per `player_id`, **no tour** |
| `data/youtube-uploads.json` | Duplicate-upload guard, keyed `tour:YYYY-MM-DD` |
| `output/YYYY-MM-DD/` | All generated assets for one calendar day, **no tour** |

`tour` today is loaded by `AppConfig` (default `"wta"`), copied onto `DailyReport`, used as the snapshot-history filter, used as the YouTube upload key, mixed into the template-narration RNG seed, and printed on the leaderboard/thumbnail. It does **not** choose `rankings_provider`, `match_provider`, `points_table_path`, or any WTA wording.

The README already sketches "add `atp_official` plugins and set `tour: atp`." That sketch is directionally correct for **data**, and incomplete for branding, pronouns, persistence collisions, and the missing ATP source.

---

## 3. WTA-Specific Dependencies

Legend for "should remain tour-specific": **keep as WTA plugin/data** vs **generalize via tour profile / config**. Difficulty is for making ATP work *without changing WTA output*.

### 3.1 Configuration and packaging

| File / symbol | What is WTA-specific | Keep vs generalize | Difficulty |
| --- | --- | --- | --- |
| `config/config.example.yaml` `tour: wta` | Documented as the only shipped tour; comment says ATP = new plugins | Keep as WTA default; make `tour` actually select a profile | small |
| `AppConfig.tour` | Stored, not validated, not used to pick providers | Generalize: validate `wta`/`atp`; bind a `TourProfile` | small |
| `rankings_provider` default `wta_official` | Independent of `tour` | Keep as WTA default; ATP profile should default its own provider | small |
| `match_provider` default `best_of` + `wta_official` | WTA-first source list | Same as above | small |
| `tournament_status.points_table_path` default `data/wta_points_table.yaml` | WTA points | Keep WTA file; ATP gets its own YAML, selected by profile | small |
| `featured_player.player_id: "325410"` | Emma Navarro's WTA API id | Remain config, not code. ATP needs a different player (or disabled) | trivial |
| `tournament_preferences: [Grand Slam, WTA 1000]` | WTA 1000 | Tour-specific config (unused in pipeline today) | trivial |
| `git.commit_message_template` `"Daily WTA Update {date}"` | WTA in commit text | Tour profile / config template | trivial |
| `network.user_agent` `"wta-daily/0.1"` | Product name | Optional later; do not change for WTA | trivial |
| `pyproject.toml` name `wta-daily`, script `wta-daily`, package `wta_daily` | Entire installable name | **Keep.** Renaming would churn production cron/systemd/imports for no ATP gain | n/a |
| `deploy/cron/wta-daily.cron`, `deploy/systemd/wta-daily.*` | One WTA job, one lockfile, one config path | Keep WTA units; add a second ATP unit later rather than one dual-tour process | small |
| `wta_daily/exceptions.py` `WtaDailyError` | Name only | Keep. Cosmetic rename is not worth it | n/a |

### 3.2 Rankings

| File / symbol | What is WTA-specific | Keep vs generalize | Difficulty |
| --- | --- | --- | --- |
| `plugins/rankings/wta_official.py` `WtaOfficialRankingsProvider` | `api.wtatennis.com` `/players/ranked`, `rankedAt`, nested `player.fullName` | **Keep as WTA plugin.** Do not stretch this class to ATP | n/a |
| `plugins/wta_api_client.py` | WTA base URL, WTA endpoints, WTA api_usage categories | **Keep WTA-only** | n/a |
| `models.PlayerRanking` | Docstrings say "WTA"; fields are generic | Generalize comments later; **do not change the model** | trivial |
| `movement.py` `is_same_official_ranking_list` / `resolve_official_ranking` | Logic is generic (publication date + rank/points). Warning text says "The WTA does not amend..." | Keep logic; source the warning from tour profile | small |
| `plugins/rankings/sample.py` | Tour-agnostic fixture reader | Reuse as-is; add ATP sample JSON later | trivial |

ATP ranking data **can** fit `PlayerRanking` (`rank`, `player_id`, `name`, `country_code`, `points`, `ranking_date`). Movement logic does not assume WTA structures. The missing piece is a provider that can populate that model from an ATP source with a trustworthy publication date.

### 3.3 Matches, tournaments, points, rounds

| File / symbol | What is WTA-specific | Keep vs generalize | Difficulty |
| --- | --- | --- | --- |
| `plugins/matches/wta_official.py` `WtaOfficialMatchProvider` | Entire production match path: catalogue scan, `MatchTimeStamp`, `DrawMatchType`/`MatchState`/`RoundID`, `_RELEVANT_TOUR_LEVELS` (`WTA 1000`/`WTA 500`/…), previous-year `group_id` lookback | **Keep as WTA plugin.** This is the mature, incident-hardened WTA implementation | n/a (ATP needs a sibling plugin: **significant**) |
| `plugins/matches/tournament_status.py` | Pure draw-status logic, but over WTA fixture field names (`PlayerIDA`, `DrawLevelType == "M"`, Winner `2`/`3`) | Keep WTA-specific; ATP provider maps *into* `TournamentRunStatus` rather than this parser | n/a |
| `rounds.normalize_wta_round_id` | WTA backend numeric/letter round IDs vs draw size | Keep WTA-specific. Stable `ROUND_ORDER` (`R128`…`W`) is reusable | small |
| `rounds.round_label` | Grand Slam ordinals vs "Round of N" | Reusable for ATP (same broadcast conventions) | trivial |
| `points_table.py` + `data/wta_points_table.yaml` | WTA category keys and WTA point values | Keep WTA file. Loader is already generic YAML keyed by category/round/draw size. Add `data/atp_points_table.yaml` | small |
| `reporting_day.py` | Late-night cutoff; not WTA-specific | Reuse as-is | n/a |
| `tournament_timezones.py` + `data/tournament_timezones.yaml` | Country/state → timezone; comments say WTA host countries, data is geography | Reuse; extend YAML if ATP events land in uncovered locations | small |
| `plugins/matches/best_of.py` | Generic composite. Defaults to `wta_official` + `live_tennis_api`. Tournament status "first source wins" | Reuse. ATP `best_of` sources list will differ | small |
| `plugins/matches/live_tennis_api.py` | Paid aggregator, name search, no tour filter in code | Likely reusable for ATP men if the vendor covers ATP; **unverified in this repo**. Name collision risk (same surname, mixed tours) | moderate (research + possibly a tour filter) |
| `plugins/api_tennis_client.py` `get_standings(event_type="WTA")` | Hard-coded WTA standings for player-key resolution | Smallest existing hook toward ATP (`event_type="ATP"` is plausible but **not verified here**) | small to moderate, after vendor confirmation |
| `plugins/matches/sample.py` | Tour-agnostic | Reuse | n/a |

Tournament discovery, completed-match detection, championship/final logic, and ranking-point awards for **WTA** all live in the WTA official match plugin plus the WTA points table. ATP cannot piggyback on those endpoints.

### 3.4 Player modeling

| File / symbol | What is WTA-specific | Keep vs generalize | Difficulty |
| --- | --- | --- | --- |
| `PlayerRanking` / `PlayerReport` / `FeaturedPlayerReport` | No gender, no headshot, opaque `player_id` | Reuse unchanged | n/a |
| Featured-player config | WTA player id + `america_favorite` tagline | Remain per-install config | trivial |
| `scripts_gen/name_utils.py` `first_name()` | Generic | Reuse | n/a |
| Headshots | Intentionally unused (flags only) | Reuse | n/a |
| Pronunciation overrides | **None exist** | If ATP needs them, add as tour/player config later; not a blocker | n/a |
| Gendered narration | Not on the player model; hard-coded she/her in phrase pools | Tour-level pronouns on a profile (not a per-player gender field, unless mixed-tour exhibition events appear) | small |

Same models can represent ATP players without schema changes. Player IDs are provider-specific strings; WTA and ATP official IDs must never be assumed interchangeable.

### 3.5 Narration

| File / symbol | What is WTA-specific | Keep vs generalize | Difficulty |
| --- | --- | --- | --- |
| `scripts_gen/phrases.py` `OPENERS` / `CLOSERS` | "WTA Top {n}", "women's game", "WTA Tour" | Tour-branded phrase packs, WTA pack frozen | moderate |
| Same file `POINTS_GAP_TEMPLATES`, `NEXT_RANKING_NOTES`, `FIFTY_TWO_WEEK_NOTES` | she/her; "official WTA rankings" | Pronoun + tour-name substitution. Do **not** rewrite the control flow | small |
| `scripts_gen/template_generator.py` | `"after she {match_clause}."`; log/docs she/her | One pronoun from tour profile | small |
| `scripts_gen/tournament_status_phrases.py` | she/her throughout elimination/champion/last-year copy | Pronoun substitution in the same templates | small |
| `scripts_gen/featured_player_phrases.py` | she/her; "according to the WTA" | Pronouns + `{tour}` for ranking-body name. Tagline stays editorial | small |
| `scripts_gen/openai_generator.py` `_SYSTEM_PROMPT` | "WTA Top N", she/her throughout | Prompt built from tour profile | small |
| `pipeline.py` featured-player logs | "top %d WTA rankings" | Tour display name | trivial |

Match/round/score/tournament phrasing is already tour-agnostic. Branding and pronouns are not. This should be a **tour profile + phrase formatting**, not a second template generator.

### 3.6 Graphics and video

| File / symbol | What is WTA-specific | Keep vs generalize | Difficulty |
| --- | --- | --- | --- |
| `graphics/leaderboard.py` headline | Already `{report.tour.upper()} TOP {n}` | Reuse | n/a |
| Same file footer | `"Data: WTA (api.wtatennis.com)  \|  …  \|  wta-daily"` | Tour-profile attribution string | small |
| `graphics/thumbnail.py` | Already `{report.tour.upper()} TOP {n}` | Reuse | n/a |
| `graphics/player_card.py` / `featured_card.py` | No WTA wordmark; "YESTERDAY'S MATCH" / "FEATURED PLAYER" | Reuse | n/a |
| `video/ffmpeg_assembler.py` | Image sequencing only | Reuse | n/a |
| Theme colors / layout | Neutral, not women's-tour branded | Reuse; optional ATP theme later, not required | n/a |

No separate rendering pipeline is needed. Titles/descriptions are the branding gap, not the PNG/MP4 pipeline.

### 3.7 YouTube publishing

| File / symbol | What is WTA-specific | Keep vs generalize | Difficulty |
| --- | --- | --- | --- |
| `title.py` `generate_title` | **Hard-codes `"WTA Top {n} Update"`** even though `report.tour` exists | Use `report.tour.upper()` (or profile display name). WTA tests must keep the current string | small |
| `youtube_description.py` | Hard-codes "WTA Top {n}" four times | Same | small |
| `youtube/uploader.py` | Generic upload; no tags; destination = OAuth token file | Keep generic. **Do not share WTA and ATP channels by default.** Separate `token_path` / client secret per tour | n/a for core logic |
| `YouTubeConfig` | No channel id / playlist field | Add only if a single Google client must publish to two channels; otherwise two token files are enough | small |
| Duplicate protection | Already `(date, tour)` | Reuse | n/a |
| Category `17` Sports | Fine for both tours | Reuse | n/a |

Upload mechanics are tour-agnostic. Title/description branding is accidentally WTA-specific. Destination is already outside tennis logic (OAuth files).

### 3.8 Persistence (see also §6)

| File / symbol | Collision risk | Keep vs generalize | Difficulty |
| --- | --- | --- | --- |
| `RankingsSnapshotStore` | Tour-scoped entries | Keep | n/a |
| `YouTubeUploadStore` | Tour-scoped keys | Keep | n/a |
| `TournamentStatusStore` | Keyed only by `player_id` | Must add tour (or directory namespace) | small |
| `players.json` | Keyed only by `player_id` | Same | small |
| `DailyOutputStore` `output/<date>/` | Same-day WTA and ATP overwrite each other | Namespace `output/<tour>/<date>/` **or** separate `output_dir` per config | small |
| Git automation staged paths | Hard-coded `data/rankings-history.json` etc. | Follow whatever namespace is chosen | trivial |

### 3.9 Tests that pin WTA output (must remain)

These are the regression baseline, not obstacles:

- `tests/test_title.py` — exact `"WTA Top 10 Update — …"`
- `tests/test_youtube_description.py` — `"latest WTA Top 1 rankings"`
- `tests/test_pipeline_integration.py` — `"WTA Top 5 Update — August 17, 2026"`
- `tests/test_youtube_uploader.py` — WTA title passed to the API
- `tests/test_wta_official_*`, `tests/test_wta_api_client.py`, `tests/test_points_table.py`, `tests/test_rounds.py`, `tests/test_tournament_status.py` — WTA provider/points/round behavior
- Narration tests that assume she/her and WTA openers (`test_script_generator.py`, `test_featured_player_narration.py`, `test_tournament_status_narration.py`, `test_openai_generator.py`)

---

## 4. Already-Reusable Components

Little or no modification for ATP, once an ATP provider fills the same models:

- `DailyPipeline` orchestration (fetch → movement → matches → report → script → graphics → voice → video → YouTube → git)
- `RankingsProvider` / `MatchProvider` / `ScriptGenerator` / `GraphicsRenderer` / `VoiceSynthesizer` / `VideoAssembler` ABCs and `PluginRegistry`
- `BestOfMatchProvider` composition pattern
- `PlayerRanking`, `MatchResult`, `MatchLookupResult`, `PlayerReport`, `FeaturedPlayerReport`, `DailyReport`, `TournamentRunStatus`, `Movement`
- `compute_movement` / `is_same_official_ranking_list` / `resolve_official_ranking` (warning text aside)
- `RankingsSnapshotStore` tour filtering; `YouTubeUploadStore` tour keys
- `DailyOutputStore` layout (paths may gain a tour segment; the class shape stays)
- `reporting_day` cutoff logic
- `tournament_timezones` geography table
- `PointsTable` YAML loader (new data file, same code)
- `round_label` / `ROUND_ORDER` (not `normalize_wta_round_id`)
- `tournament_context.most_relevant_tournament`
- Graphics: leaderboard/thumbnail tour headline, player cards, featured card, flags, fonts, theme
- ffmpeg assembler and ElevenLabs synthesizer (pronouns are in the script, not the audio engine)
- YouTube auth/upload, minus title/description strings
- HTTP client, api_usage counters, logging, CLI flags (`--date`, `--upload-youtube`)
- Sample rankings/matches providers
- Legal approach: no player headshots

---

## 5. Data Provider Strategy

### 5.1 What the repo actually knows

The production WTA rankings source is the unofficial-but-public JSON backend `https://api.wtatennis.com/tennis`. Match freshness depends on that same backend's **tournament** feed, with `livetennisapi.com` as paid backup and `api-tennis.com` implemented but not defaulted.

The README already records that **Sportradar is the exclusive ATP rights partner**, with no hobby-friendly self-serve production pricing. It does **not** document an `api.atptour.com`-class free official JSON API, and this repository does not contain one.

**From the repository alone, an appropriate official ATP provider cannot be determined.** Treating ATP as "the same API with a different `tour` flag" would be a guess, and a dangerous one.

### 5.2 Candidates that would need external research (not implementation)

1. **Whether ATP publishes a public JSON backend analogous to `api.wtatennis.com`.** If it exists and is legally usable for this hobby/YouTube use case, that is the preferred rankings + (if possible) draw-status source, as a new plugin, not a fork of `WtaOfficialApiClient`.
2. **`api-tennis.com` `get_standings(event_type=…)`.** The client already parameterizes `event_type` and hard-codes `"WTA"` at the match-provider call site. If `"ATP"` returns official-looking ATP singles standings and dated fixtures, this is the fastest *possible* rankings+matches path already in-tree. Coverage, ranking publication date, draw visibility, and the known one-day date drift must be re-verified on ATP data. This repo has not done that.
3. **`livetennisapi.com`.** Likely has ATP player histories (it is a mixed-tour aggregator), but there is no tour filter in the current client. Name search without a tour/sex constraint is riskier for men's tennis (more namesakes). It also does **not** populate `tournament_status` today.
4. **Sportradar / other licensed ATP feeds.** Documented as enterprise-priced. Only relevant if the product later funds it.
5. **Sackmann/Tennis Abstract `tennis_atp`.** Same problem as `tennis_wta`: CC BY-NC-SA and not same-day. Unsuitable for a daily, potentially monetized video.

Until (1) or (2) is proven, ATP support should not be scheduled as "write `atp_official.py` against a known URL."

### 5.3 Interface an ATP provider must satisfy

An ATP rankings plugin is enough if it implements:

```text
RankingsProvider.get_top_n(n) -> list[PlayerRanking]
```

with:

- ascending official singles rank
- stable opaque `player_id` (ATP's own ids, never WTA ids)
- `fullName`-equivalent display name
- ISO country code if available
- ranking points as published
- `ranking_date` set when the source exposes a list publication date (needed so a match cannot look like a ranking change)

An ATP match plugin is enough for a *basic* daily video if it implements:

```text
MatchProvider.get_matches_for_date(players, target_date) -> MatchLookupResult
```

populating `MatchResult` (`opponent`, `tournament`, `round` or `None`, `score`, `won`, `match_date`, optional `surface`) and distinguishing "did not play" from "unresolved."

A *feature-complete* ATP video, matching current WTA narration, also needs `MatchLookupResult.tournament_status`:

- `ACTIVE` / `ELIMINATED` / `CHAMPION` / `DID_NOT_PARTICIPATE` / `UNKNOWN`
- `round_reached` in the stable `ROUND_ORDER` vocabulary (`R128`…`W`, not vendor codes)
- `eliminated_by`, `category` (e.g. `ATP 1000`), `tournament_group_id` for year-over-year identity
- `points_earned` via `PointsTable.lookup` against an ATP points YAML

`get_latest_match` can stay as the poorer fallback; WTA production taught that day-first lookup is what keeps "yesterday" honest.

`live_tennis_api` and `api_tennis` currently **never** fill `tournament_status`. If ATP has no draw-visible source, elimination/champion/points/last-year narration would simply stay off for ATP (the WTA path already degrades that way when `wta_official` is not in play). That is acceptable for an MVP; it is not feature parity.

---

## 6. Persistence / Cache Risks

Assume the same Raspberry Pi, same clone, and someone sets `tour: atp` in the existing `config.yaml` without changing `data_dir` / `output_dir`.

| Artifact | Isolated today? | If both tours run |
| --- | --- | --- |
| `data/rankings-history.json` | Yes, per-entry `tour` | Safe. ATP snapshots sit beside WTA. Tests already cover `get_previous_snapshot` ignoring the other tour. |
| `data/youtube-uploads.json` | Yes, key `tour:date` | Safe. An ATP upload will not skip/duplicate a WTA video. |
| `data/tournament-status-history.json` | **No** | **Unsafe.** Keyed only by `player_id`. Numeric ids from two tours can collide; even without collision, a shared file mixes "already told this elimination" across tours. |
| `data/players.json` | **No** | **Unsafe.** Same `player_id` from different providers overwrites name/country. |
| `output/YYYY-MM-DD/` | **No** | **Unsafe.** Same-day ATP run replaces WTA `report.json`, `video.mp4`, thumbnail, script, cards. `--upload-youtube` would then publish the wrong package. |
| `logs/` | Date-based, no tour | Log interleaving only; low risk |
| `secrets/youtube_token.json` | Shared | **Operational risk:** ATP upload would go to the WTA-authenticated channel unless `token_path` differs |
| Rankings snapshot "NEW" semantics | Tour-filtered, but scoped to `top_n` | Fine if tours don't share snapshots (they don't) |

`data_dir` and `output_dir` are already configurable. Two complete configs:

```yaml
# config/wta.yaml
tour: wta
data_dir: data/wta
output_dir: output/wta
```

```yaml
# config/atp.yaml
tour: atp
data_dir: data/atp
output_dir: output/atp
```

would isolate **everything** including the currently unscoped files, with **zero code change**. That is the safest operational pattern for a Pi that runs both jobs.

Code-level namespacing (`output/{tour}/{date}/`, tour key on tournament-status and players cache) is still worth doing so a single-config "Pam switch" cannot clobber WTA history. Prefer **directory isolation via config first**, then in-file tour keys as defense in depth. Do not migrate existing WTA JSON into a new layout without a one-time, tested, WTA-only compatibility read path.

Recommended end state if both tours share one `data_dir`:

```text
data/rankings-history.json          # already has tour per entry
data/youtube-uploads.json           # already keyed tour:date
data/players.json                   # nest or prefix by tour
data/tournament-status-history.json # nest or prefix by tour
output/wta/YYYY-MM-DD/
output/atp/YYYY-MM-DD/
```

Do not put ATP rankings into the WTA snapshot's `rankings` array. The store already prevents that when `tour` is set correctly.

---

## 7. Proposed Architecture

Smallest change that supports two tours without duplicating the pipeline:

```text
                 DailyPipeline  (unchanged control flow)
                         |
                    AppConfig
                         |
                   TourProfile          <-- new, selected once from config.tour
                   (branding, pronouns,
                    default providers,
                    points table path,
                    attribution footer)
                         |
          +--------------+--------------+
          |                             |
   RankingsProvider              MatchProvider
   wta_official | atp_*          wta_official | atp_* | best_of(...)
          |                             |
          +--------------+--------------+
                         |
              Normalized models (already exist)
                         |
         narration / title / description  <-- consume TourProfile, not if-tour
                         |
              graphics / video / YouTube
```

### 7.1 `TourProfile` (one selection boundary)

A frozen dataclass, not a scatter of conditionals. Rough shape:

```text
id: "wta" | "atp"
display_name: "WTA" | "ATP"                  # titles, "WTA Top 10"
tour_long_name: "WTA Tour" | "ATP Tour"      # closers
game_label: "women's game" | "men's game"    # one closer
pronouns: subject/object/possessive          # she/her/her vs he/him/his
points_table_path
ranking_attribution                            # leaderboard footer
default_rankings_provider / default_match_provider  # only used when config omits them, or documented as the profile's recommended block
```

WTA's profile must reproduce **today's exact strings** so existing tests stay green without rewriting assertions.

`AppConfig.from_mapping` is the one place that maps `tour: wta|atp` → profile. Downstream modules take `report.tour` / profile fields, never `if tour == "atp"`.

### 7.2 What not to do

- Do not rename `wta_daily` / `wta-daily` as part of ATP work.
- Do not create `atp_daily/` or copy `DailyPipeline`.
- Do not generalize `WtaOfficialMatchProvider` into a "tennis official" client. ATP's API, if any, will differ. Keep WTA code stable.
- Do not add per-player gender to models unless a future mixed event requires it. Tour-level pronouns are enough for Top 10 products.
- Do not force ATP and WTA onto one YouTube token.

### 7.3 Provider wiring

Keep explicit YAML provider blocks (they already exist and production WTA depends on them). Optionally, a tour profile may supply defaults when those blocks are omitted. Production ATP config should still list providers explicitly so a WTA `best_of` source cannot be left accidentally enabled.

### 7.4 Package layout for ATP code when it exists

```text
wta_daily/plugins/rankings/atp_....py
wta_daily/plugins/matches/atp_....py
wta_daily/plugins/atp_..._client.py     # only if a dedicated HTTP client is needed
data/atp_points_table.yaml
data/sample/atp_rankings_sample.json    # optional
```

The `wta_daily` import path stays. It is a historical package name, not a tour constraint.

---

## 8. Implementation Sequence

Each stage should leave WTA operational and, where possible, byte-identical for WTA configs.

### Stage 0 — This audit (no code)

Review and agree boundaries: tour profile vs directory isolation vs provider research.

### Stage 1 — Isolate tour branding (safe, no ATP data)

Make `generate_title` / `generate_description` use `report.tour` (WTA still renders "WTA"). Extract WTA openers/closers/pronouns into a WTA tour profile whose strings match production. Template + OpenAI prompt consume the profile. Leaderboard footer uses profile attribution.

**WTA lock:** existing title/description/script tests must pass unchanged. Add a parallel ATP-string unit test with a fake `DailyReport(tour="atp")` and sample players — still no ATP API.

### Stage 2 — Persistence namespacing (safe, no ATP data)

- Include `tour` in `TournamentStatusStore` keys (default missing tour to `"wta"` so existing files keep working).
- Include `tour` in `players.json` (same default).
- Namespace `DailyOutputStore` by tour **or** document+example `data_dir`/`output_dir` per tour and add a guard that refuses to write ATP into a directory that already contains a different tour's `report.json` for that date.
- Git automation follows the new paths.

**WTA lock:** snapshot-store and tournament-status-store tests plus a migration test that reads a current WTA `tournament-status-history.json` without a tour field.

### Stage 3 — ATP points table as data only

Add `data/atp_points_table.yaml` (ATP 1000/500/250, Grand Slam, Finals caveats) and point `TourProfile` at it. `PointsTable` code unchanged. No live ATP yet.

**WTA lock:** `tests/test_points_table.py` still loads the WTA file by default.

### Stage 4 — ATP data-source spike (research PR, still no production ATP)

Prove or reject:

- official ATP JSON availability
- `api-tennis.com` `event_type=ATP`
- `livetennisapi.com` ATP coverage and name-resolution collisions
- whether any source can populate `tournament_status`

Write findings into this doc or a short follow-up. **Do not implement a guessed official client.**

### Stage 5 — ATP providers behind the existing interfaces

Implement whatever Stage 4 selected, registered as new plugin names. Sample ATP fixtures for offline tests. Production `config.example.yaml` stays WTA. An `config/config.atp.example.yaml` shows the ATP block.

WTA `wta_official` / `best_of` defaults unchanged.

### Stage 6 — Dual-run operations

Second systemd/cron unit, second config, second YouTube token path, optional second featured player. `flock` lockfiles must differ. Do not make one process emit both videos.

### Stage 7 — Feature-parity extras (only after a working ATP Top 10 video)

Draw-status/previous-year lookback for ATP if a draw feed exists; ATP-specific featured-player tagline; timezone YAML gaps; pronunciation list if names require it.

---

## 9. Regression / Test Strategy

WTA production behavior is the baseline. ATP work must not be accepted if it quietly retunes WTA copy, ranking movement, match dating, or elimination narration.

### 9.1 Treat current tests as a freeze

Run the full existing suite on every ATP-related PR. In particular:

- Provider: `test_wta_official_rankings_provider`, `test_wta_official_match_provider`, `test_wta_api_client`, `test_best_of_match_provider`, `test_live_tennis_api_match_provider`, `test_api_tennis_match_provider`
- Domain: `test_movement`, `test_rounds`, `test_points_table`, `test_reporting_day`, `test_tournament_status`, `test_tournament_status_store`, `test_snapshot_store`
- Output: `test_title`, `test_youtube_description`, `test_script_generator`, `test_tournament_status_narration`, `test_featured_player_narration`, `test_openai_generator`, `test_graphics`, `test_pipeline_integration`

Do not "flex" those assertions to accept both tours. Keep WTA strings exact; add ATP cases beside them.

### 9.2 Golden WTA narration (recommended before Stage 1 merges)

Add one frozen WTA script test: fixed `DailyReport(tour="wta")` + known RNG seed (`date:tour` is already the seed) → exact `script.txt`. That catches accidental pronoun/branding refactors.

### 9.3 New tests required before ATP can be called complete

- Tour profile: `tour: wta` yields today's title/opener/pronouns; `tour: atp` yields ATP equivalents without changing WTA.
- Persistence: ATP snapshot does not alter WTA previous-rank; ATP elimination does not mark a WTA player "already told"; same calendar date can store two output folders.
- ATP rankings provider (once it exists): maps vendor payload → `PlayerRanking`, including `ranking_date` if available.
- ATP match provider: day-first "played / not played / unresolved"; never uses tournament start date as `match_date`.
- Offline ATP sample pipeline: `tour: atp` + sample providers produce `ATP Top N` title/thumbnail headline and he/him script.
- Dual-config smoke: two `data_dir`s on one fixture tree do not cross-write.

### 9.4 What not to share

Do not reuse WTA live HTTP cassettes for ATP. Do not point ATP tests at `api.wtatennis.com`. Do not weaken `test_wta_official_match_provider` to accommodate a shared helper that ATP needs.

---

## 10. Risks / Unknowns

1. **ATP official rankings/match API.** Largest blocker. Repo cannot name a WTA-equivalent free official ATP JSON API. Sportradar exclusivity is documented here as a commercial wall, not as an integration plan.
2. **Tournament-draw visibility.** Without it, ATP videos lose elimination/champion/points/last-year lines. WTA already knows those lines are provider-gated; ATP may ship without them at first.
3. **ATP vs WTA points schedules.** Similar ladder, different numbers and category names (ATP 1000 vs WTA 1000, United Cup, Next Gen, ATP Finals round-robin). Must be a separate YAML, never the WTA file with a prefix.
4. **`livetennisapi` / `api-tennis` ATP quality.** WTA live testing found coverage gaps and one-day date drift. ATP may be better, worse, or different. Re-test; do not inherit WTA conclusions.
5. **Player id collisions** if both tours share `players.json` / tournament-status files.
6. **Same-day output overwrite** if both tours share `output_dir`.
7. **YouTube channel mix-up** if both tours share one OAuth token.
8. **Pronoun edge cases.** Tour-level he/she is correct for ATP/WTA Top 10. Exhibition mixed events are out of scope.
9. **Package name vs product name.** Keeping `wta_daily` while publishing ATP videos is slightly awkward and far safer than a rename. Cron, systemd, and `python -m wta_daily.cli` should stay.
10. **Legal/ToS.** Same gray area as WTA: unofficial or aggregator APIs plus YouTube narration. ATP licensed data is stricter on paper (Sportradar). Confirm terms before shipping ATP commercially.
11. **Featured player.** Emma Navarro's WTA id is meaningless on ATP. Disable or reconfigure; do not resolve by name across tours.
12. **Best-of-five Grand Slam scoring.** Models already store a score string; narration already reads it. Unlikely to need a new model. Confirm ATP provider score formatting (tiebreaks, retirements).
13. **README optimism.** Architecture section currently says ATP is "add two plugins and set `tour: atp`." That understates branding, pronouns, persistence, and the missing data source. This audit is the correction.

---

## 11. The "Pam Switch" Test

> After the proposed work is complete, how close can we realistically get to changing only `tour: wta` to `tour: atp` and having the application produce the corresponding daily Top 10 video?

**Close on branding and plumbing; not honest as a one-line production switch.**

If Stages 1–5 are done well, flipping `tour` *in isolation* on today's production config should:

- write ATP snapshots under `tour: atp` without erasing WTA history
- say "ATP Top 10" on title, description, thumbnail, leaderboard
- use he/him and "men's game" / "ATP Tour" in narration
- look up ATP points if the ATP provider fills tournament status

It will **not**, by itself, be a correct production ATP run unless these also differ — and they *should* differ:

| Setting | Why it must differ |
| --- | --- |
| `rankings_provider` | There is no ATP implementation of `wta_official`. Using it on `tour: atp` would still fetch WTA women and then brand them as ATP. |
| `match_provider` / `best_of.sources` | Same. WTA catalogue scan cannot be the ATP match source. |
| `tournament_status.points_table_path` | ATP must not use `data/wta_points_table.yaml`. A tour profile can set this automatically. |
| `featured_player` | WTA player id 325410 is not an ATP player. Disable or point at an ATP id from the ATP provider. |
| `youtube.token_path` (and likely `client_secret_path`) | Publishing destination is not tennis logic. ATP should not land on the WTA channel unless that is an explicit later choice. |
| `data_dir` / `output_dir` **or** the Stage 2 namespaces | Defense against history/output clobber if both jobs share a checkout. |
| Paid API keys | Only if the ATP match mix still uses `live_tennis_api` / `api_tennis`. Same env vars may work; coverage must be verified. |
| `git.commit_message_template` | Optional; profile can default it. |
| Scheduler | A second cron/systemd unit (different config, different flock lock). One process, one tour per run. |

**Realistic Pam-switch after the work:**

```yaml
tour: atp
# providers either omitted (profile defaults) or an explicit ATP block
featured_player:
  enabled: false
youtube:
  token_path: secrets/youtube_token_atp.json
data_dir: data/atp
output_dir: output/atp
```

That is a **small config file**, not a second application. It is not literally one key. Making it literally one key would require auto-selecting providers from `tour` **and** encoding YouTube destination and featured player into the tour profile, which couples publishing and editorial choices to tennis logic — the opposite of the requested split.

**Hard stop if Stage 4 finds no usable ATP rankings source:** the switch cannot produce a truthful ATP Top 10, regardless of branding. The pipeline will be ready; the data will not.

---

## Appendix A — `tour` usage map (current code)

| Consumer | Uses `tour`? | Effect today |
| --- | --- | --- |
| `AppConfig.tour` | stored | Default `"wta"`; no enum |
| `DailyReport.tour` | yes | Serialized to `report.json` |
| `RankingsSnapshotStore` | yes | Filters/saves snapshots |
| `YouTubeUploadStore` | yes | Duplicate key |
| `TemplateScriptGenerator` RNG | yes | Seed `date:tour` only |
| Leaderboard / thumbnail | yes | `"WTA TOP 10"` / would show `"ATP TOP 10"` |
| `generate_title` | **no** | Always `"WTA Top N Update"` |
| `generate_description` | **no** | Always WTA copy |
| Phrase pools / OpenAI prompt | **no** | WTA + she/her |
| Provider construction | **no** | Always whatever YAML names |
| `TournamentStatusStore` | **no** | Collision risk |
| `players.json` | **no** | Collision risk |
| `DailyOutputStore` | **no** | Same-day overwrite risk |

So `tour: wta` is **partially real** (storage + two graphics) and **mostly not a product switch**. That is the gap ATP work should close, incrementally, without rewriting the WTA pipeline.
