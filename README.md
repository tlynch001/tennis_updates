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
| **`api.wtatennis.com` (used by this project)** | ✅ Selected | The WTA's own public JSON backend - the same API that powers wtatennis.com. Confirmed live: no API key, no auth header, no `Origin`/`Referer` gate, and `wtatennis.com/robots.txt` returns `Disallow:` (empty) - automated access is not blocked. It's plain JSON over HTTPS, not HTML scraping. |
| Sackmann/Tennis Abstract GitHub data (`tennis_wta`) | ❌ Not used for daily data | Excellent, openly-hosted historical rankings/results, but licensed **CC BY-NC-SA 4.0 (non-commercial only)** and updated on the maintainer's own schedule (not guaranteed same-day), so it doesn't fit an unattended *daily*, potentially monetized YouTube pipeline. |
| Stats Perform / Sportradar (official WTA data partners) | 🔒 Best long-term paid option | Genuinely official, contractually licensed, real-time. Enterprise sales process and pricing not suited to a hobby/unattended daily job, but this is the recommended upgrade path if the project ever needs contractual guarantees, an SLA, or richer stats (shot-by-shot, etc.). |
| RapidAPI tennis feeds (e.g. `tennis-api.com`, "Tennis API - ATP WTA ITF") | 🔒 Good paid fallback | Clean REST/JSON, explicit commercial terms, reasonably priced tiers. A solid second choice if `api.wtatennis.com` ever becomes unreliable. |
| Scraping `wtatennis.com` HTML pages directly | ❌ Rejected | Unnecessary - the JSON API above is faster, more stable, and was confirmed reachable without scraping any HTML. |
| ESPN/Sofascore/other unofficial "hidden" APIs | ❌ Rejected | Similar shape to the WTA's own API but with murkier terms of use and no official relationship to the data. No reason to use a third party's undocumented endpoint when the primary source's own undocumented endpoint is available and unrestricted. |

**Recommendation, and what's implemented:** use the WTA's own
`api.wtatennis.com` backend as the default provider
(`wta_daily/plugins/rankings/wta_official.py` and
`wta_daily/plugins/matches/wta_official.py`). It is official, free, returns
structured JSON, and `robots.txt` does not disallow it. The one caveat -
documented here and in the code - is that the WTA has not published a formal
developer contract or terms of service for this specific endpoint, so it
could change or introduce rate limiting without notice. That risk is why
every provider sits behind the `RankingsProvider`/`MatchProvider` interfaces:
swapping to a paid, contractually-licensed provider (Stats Perform/Sportradar
or a RapidAPI tennis feed) later is a matter of adding one new plugin module
and changing two lines in `config.yaml` - never a rewrite. A fully offline
`sample` provider (`wta_daily/plugins/rankings/sample.py`,
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
- `rankings_provider` / `match_provider` - `{provider: <name>, ...options}`;
  `<name>` is looked up in the plugin registry (see below).
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
       3. MatchProvider.get_latest_match() x N  <- plugin: matches_registry  (per-player try/except)
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

- **One player's failure never aborts the run.** `DailyPipeline._safe_get_latest_match`
  catches any exception from the match provider per player, records it on
  that player's `match_error` field (visible in `report.json`), appends it to
  the report's `errors` list, logs it, and moves on to the next player. This
  is covered by `tests/test_pipeline_integration.py::test_pipeline_continues_when_one_players_match_fails`.
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

70+ unit/integration tests cover models, movement math (including the
"unknown" vs "new" distinction), country/flag resolution, config loading,
the plugin registry, snapshot persistence, the sample providers, the
`wta_official` match provider's date-recovery and bye/walkover/doubles
filtering logic (mocked HTTP - see
`tests/test_wta_official_match_provider.py`), the template script generator
(including the "mention movement only when it changed", "never say a
baseline run's players are new", "the sign-off is always last" and "no
verbatim-identical script two days in a row" behaviors), graphics rendering,
and a full end-to-end pipeline run (including the per-player-failure-isolation
scenario) - all using the offline `sample` providers or mocked HTTP
responses, so `pytest` never makes a real network call.

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
