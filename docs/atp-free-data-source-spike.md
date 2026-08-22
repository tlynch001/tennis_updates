# ATP Free Data-Source Spike

**Status:** research and recommendation only. No provider implementation, no production WTA change, no scheduler or YouTube work, no merge of PR #19.

**Research date:** 22 August 2026 (UTC).

**Hard constraint:** ATP data-source recurring cost must be **$0**. Feature parity with WTA is not required.

**Question:** What is the best useful ATP Top 10 video we can build using only zero-cost data sources?

**Chosen outcome:** **Outcome C — Free weekly ATP is better.**

This document supersedes the paid-API recommendation in [`docs/atp-data-source-spike.md`](atp-data-source-spike.md) (PR #18, now on `main`). That earlier spike asked whether a WTA-comparable ATP product was possible. This spike asks a different question under a different budget. PR #19's api-tennis.com implementation is experimental reference only and is **not** the target architecture.

---

## Evidence legend

Claims are tagged:

- **Documented** — current vendor, Wikimedia, or site documentation retrieved for this spike.
- **Observed** — HTTP response or file contents seen during this spike (22 August 2026).
- **Repo-observed** — earlier repository notes. Not re-run unless stated.
- **Inference** — reasonable conclusion from documented/observed facts; not independently proven.
- **Unknown** — not verified; do not treat as a fact.

This environment had no BALLDONTLIE, RapidAPI, LiveTennisAPI, or api-tennis keys. Authenticated payloads for those vendors were **not** fetched. Free public surfaces (Wikipedia API, TennisMyLife published CSVs, unauthenticated API probes) **were** fetched.

---

## 1. Executive Recommendation

**Build a weekly ATP Top 10 rankings video for $0. Do not build a daily ATP show until a free, date-accurate match source is proven with a real key or a clearly licensed public file.**

What we can honestly ship at $0:

| Include in ATP v1 | Source | Why it is enough |
| --- | --- | --- |
| Current ATP Top 10 | BALLDONTLIE free rankings | Documented permanent $0 tier; rank, points, movement, `ranking_date`, stable `player.id` |
| Ranking points | same | Documented on the free rankings object |
| Ranking-list date | same | Documented `ranking_date` |
| Movement vs last week | same + our snapshot store | Vendor `movement` is a bonus; the pipeline already computes movement from stored snapshots |
| “New official list” vs same list re-fetched | same | `ranking_date` is the field WTA already uses for this distinction |

What we should **not** promise in ATP v1:

- Yesterday’s completed matches as a daily recap
- Elimination / champion / points-earned / previous-year lines
- Draw traversal or featured-player analysis
- Architectural symmetry with the WTA morning job

Why weekly, not daily:

1. **Official ATP rankings are weekly.** The ATP rankings FAQ and Wikipedia both state that PIF ATP Rankings update on Mondays (or at the end of a two-week event). **Documented.** A daily rankings video would repeat the same official list on Tuesday–Sunday.
2. **No $0 source we could fully validate supplies yesterday-dated completed ATP matches** with terms that are clean enough to build an unattended daily product on.
3. A truthful weekly “ATP Top 10 Rankings Update” is better YouTube content than six muted reruns plus one uncertain match scrape.

BALLDONTLIE matches remain **PAID** (ALL-STAR, $9.99/mo). **Documented.** That does not disqualify BALLDONTLIE as the free rankings provider.

PR #19 should be **closed, not merged**. Keep it as reference. The next implementation PR should be a new free rankings-only path, not a rewrite of the paid api-tennis plugins.

---

## 2. Zero-Cost Data Matrix

Only sources that can contribute something at **$0 recurring**. Paid-only capabilities are marked so they are **not** part of the recommended architecture.

Status values: **FREE** / **FREE TRIAL** / **PAID** / **No** / **Partial** / **Unknown**.

| Field | BALLDONTLIE ATP | Wikipedia MediaWiki | TennisMyLife published CSVs | LiveTennisAPI FREE | tennis-api.com RapidAPI BASIC | Jeff Sackmann `tennis_atp` |
| --- | --- | --- | --- | --- | --- | --- |
| Cost class | **FREE** (rankings/players/tournaments) | **FREE** | **FREE** file download; license conflict noted in §5 | **FREE** (live/upcoming/players only) | RapidAPI JSON: **FREE** $0 BASIC; vendor page: **FREE TRIAL** | **FREE** download; **CC BY-NC-SA 4.0** |
| Rankings | **FREE** | **FREE** | No dedicated current table found | Per-player rank on FREE player objects; **listing is PAID (PRO)** | Rankings listed on BASIC; **not live-tested** | Historical ranking CSVs; not a current daily table |
| Ranking points | **FREE** | **FREE** | Present on match rows as at-the-time points, not a current table | Documented on FREE player objects | Documented; **not live-tested** | Historical |
| Ranking date | **FREE** (`ranking_date`) | Partial (`as-of` / `{{As of}}`; can lag the edit) | No | No on FREE listing | Documented examples include `updated`; **Unknown** | Weekly historical dates |
| Stable player ID | **FREE** (`player.id`) | Wikipedia title / article name only | ATP-style IDs (`S0AG`, `A0E2`) | Numeric; shared when rostered | Mixed numeric and slug IDs **Documented** | Sackmann numeric IDs |
| Matches | **PAID** (ALL-STAR) | Tournament pages only; editor-updated wikitext | Year file + `ongoing_tourneys.csv` | Live/upcoming **FREE**; completed **PAID (BASIC)** | Fixtures/results listed on BASIC; **not live-tested** | Season CSVs; not same-day |
| Score | PAID | Partial on draw pages | Yes on CSV rows **Observed** | FREE only while live/upcoming | Documented; **not live-tested** | Yes |
| Tournament | PAID | Page title | Yes **Observed** | FREE for live/upcoming | Documented | Yes |
| Round | PAID | Partial | Yes (`R128`…`F`) **Observed** | FREE for live/upcoming | Documented | Yes |
| Draw | No | Wikitext brackets; brittle | No first-class draw object | No | Documented draw endpoints; likely same BASIC; **Unknown** | No |
| Freshness | Rankings: **Unknown** (no key). Docs say current rankings | Rankings edited 17 Aug 2026; labels still “as of 10/13 Aug” **Observed** | `2026.csv` through 14 Aug; `ongoing_tourneys.csv` updated 22 Aug 03:18 UTC **Observed** | Live only on FREE | **Unknown** | Last public bulk update reported May 2026; repo 404 from this environment |
| Free quota | 5 req/min; $0 **Documented** | Wikimedia etiquette; one call/week is trivial | One file GET | 30/min · **100/day** (OpenAPI 1.7.1) **Documented** | 50 req/day hard limit, 4/sec **Observed** in RapidAPI plan JSON | n/a |
| Authentication | API key required; free account **Documented**. Unauthenticated → 401 **Observed** | None for read API | None | Bearer key; free signup, no card **Documented** | RapidAPI key | None |
| Terms / licensing | Media/publishing explicitly permitted; no attribution required; no competing unmodified resale **Documented** | CC BY-SA; attribution required **Documented** | Website schema says MIT; GitHub README says non-commercial. **Conflict** | FREE usable in apps; completed history not included | RapidAPI + vendor terms; **Unknown** for YouTube | Non-commercial only — poor fit if the channel is monetized |
| Operational reliability | Small third-party; rankings endpoint documented as free | Editor-dependent; API is official | Small hobby site; year file lags; ongoing file has no match calendar date | Known vendor; FREE cannot do yesterday | New vendor; product-split confusion | Bulk, irregular updates |

Sources **excluded from the matrix** because they fail the $0 rule or the terms/safety rule:

| Source | Class | Why excluded from the architecture |
| --- | --- | --- |
| api-tennis.com | **PAID** | Starter $40/mo. This is PR #19. |
| LiveTennisAPI BASIC/PRO | **PAID** | Completed history $9.99; ranking listing $29.99 |
| BALLDONTLIE ALL-STAR | **PAID** | Matches $9.99/mo |
| Official ATP / Infosys JSON | Not a public API | `www.atptour.com` 403 Cloudflare **Repo-observed**; ajax paths robots-disallowed; Infosys backend historically encrypted |
| Sportradar official ATP | Enterprise / trial | Not $0 production |
| tennis-api.com paid plans | **PAID** | $29 / $39 / $59 / $99 |

---

## 3. Free Rankings Findings

### 3.1 BALLDONTLIE ATP — recommended rankings source

**Docs retrieved this spike:** [ATP API](https://atp.balldontlie.io/) (22 Aug 2026), [OpenAPI `atp.yml`](https://www.balldontlie.io/openapi/atp.yml), [Terms](https://balldontlie.io/terms.html) (last updated 4 August 2026).

**Documented free tier:**

| Item | Value |
| --- | --- |
| Price | $0 / month |
| Endpoints | Players, Tournaments, **Rankings** = Yes. Matches, ATP Race = No (ALL-STAR) |
| Rate limit | 5 requests / minute |
| Key | Required. “Obtain an API key by creating a free account” |
| Trial vs free | 48-hour GOAT/ALL-ACCESS trials are separate, require a payment method, and expire. Rankings are on the **permanent Free** column, not the trial |

**Documented rankings fields:** `player` (including `id`, `full_name`, `country_code`), `rank`, `points`, `movement`, `ranking_date`. Optional `date=YYYY-MM-DD` and `per_page` (max 100). Top 10 is one call.

**Quota vs our job:** one weekly (or even daily) rankings call is far under 5 req/min. Completing a Top 10 retrieval on the free quota is **Documented** as feasible.

**Observed this spike:**

```text
GET https://api.balldontlie.io/atp/v1/rankings?per_page=10
HTTP 401
Unauthorized
```

Same for `/atp/v1/players?search=Sinner`. That confirms the endpoint exists and requires a key. It does **not** validate live rank/points quality. **Unknown until a free key is created.**

**Signup:** `https://app.balldontlie.io/` returned HTTP 200 (SPA). Creating an account was **not** performed here. **Inference:** obtaining a free key is a normal self-serve signup. **Unknown:** whether email confirmation is instant.

**Documentation quality caveat:** the published rankings example still shows Alcaraz #1 / Sinner #2 with `ranking_date: 2026-12-01` and placeholder-ish points. **Observed** in the vendor docs. Treat examples as illustrations, not as the current list. Wikipedia and public lists on 22 Aug 2026 have Sinner #1 on 13,450 points.

**Terms relevant to YouTube (Documented, §6 of the terms):**

> You may use, copy, cache, store, archive, modify, combine, analyze, publish, display, distribute… Data. Permitted uses include … media and publishing… You do not need separate permission from us or need to credit us.

Restrictions: no competing with BALLDONTLIE as an API; no selling unmodified raw data; do not claim official ATP / endorsement status. Data is aggregated “as is.”

That is the most media-explicit $0 license found in this spike. It is still not an official ATP license.

**Verdict:** BALLDONTLIE is the best genuinely free *rankings* source. Matches being paid is irrelevant if ATP v1 is rankings-only.

### 3.2 Wikipedia / Wikimedia — validated no-key fallback

**Official programmatic access:** English Wikipedia Action API and REST API. **Documented** etiquette: descriptive User-Agent with contact info, serial requests, `maxlag` for unattended jobs, JSON. [API:Etiquette](https://www.mediawiki.org/wiki/API:Etiquette).

**Observed this spike (22 Aug 2026):**

| Resource | Result |
| --- | --- |
| `Module:ATP rankings/data/singles.json` via `action=query&prop=revisions` | HTTP 200 JSON. Revision `2026-08-17T20:08:23Z`. `current.as-of` = **Aug 13, 2026**. Flattened per-country rows give a full ranking list with `name`, `points`, `rank`. Top 10: Sinner 13450, Alcaraz 8160, Zverev 8090, Auger-Aliassime 4740, Djokovic 3760, Shelton 3670, Medvedev 3580, de Minaur 3560, Fritz 3375, Cobolli 3330 |
| `Current tennis rankings` wikitext | HTTP 200. Same Top 10 and points. Header `{{As of|2026|8|10}}`. Last revision `2026-08-17T23:15:47Z` comment `/* ATP singles */` |

**Freshness judgment:**

- Official lists update Mondays. 17 August 2026 was a Monday. Editors touched the page that day. **Observed.**
- The visible “as of” labels still say 10 August or 13 August. **Observed.** So the publication date we can print is weaker than WTA’s `rankedAt`.
- We must not invent a ranking date of “today.” Use the module `as-of` / template date, or leave `ranking_date` unset.

**IDs:** Wikipedia article titles (`Jannik Sinner`), not ATP or BALLDONTLIE IDs. Fine for a Top 10 snapshot if we treat the title as `player_id`, or maintain a ten-row map.

**License:** page content is CC BY-SA. Attribution in the YouTube description is required if we reproduce the compilation. Sports facts themselves are not a substitute for following Wikimedia license terms. **Documented** generally; we did not request legal review.

**Verdict:** acceptable $0 fallback and the only rankings source **live-validated** in this environment. Prefer BALLDONTLIE for stable numeric IDs and `ranking_date` once a free key exists.

### 3.3 LiveTennisAPI FREE player ranks — not a ranking table

**Docs retrieved:** homepage [livetennisapi.com](https://livetennisapi.com/), OpenAPI **v1.7.1**, HTML reference (stale vs OpenAPI).

**Documented (OpenAPI 1.7.1, current):**

| Plan | Rankings | Completed matches | Quota |
| --- | --- | --- | --- |
| FREE | No listing. `GET /players/{id}` includes `ranking`, `ranking_points`, `ranking_movement` | No. `status=completed` → `403 upgrade_required` | 30/min · **100/day** |
| BASIC $9.99 | No listing | Yes | 60/min · 1,000/day |
| PRO $29.99 | Full `/rankings?system=` listing | Yes | 300/min · 10,000/day |

**Change vs PR #18:** FREE daily quota is now **100/day**, not 1,000/day. Homepage marketing also lists `/rankings?as_of=` under Ultra; OpenAPI still says the rank-ordered listing is **PRO**. Trust OpenAPI for gating; treat the homepage table as marketing.

A watchlist of ~15–25 known IDs could reconstruct an approximate Top 10 from FREE player objects. That is **not** a published ranking table. A new entrant outside the watchlist would be silently omitted. **Not recommended.**

**Observed:** `GET /api/public/v1/health` → `{"status":"ok","version":"v1"}`.

### 3.4 tennis-api.com rankings

See §4.2. Rankings are listed on the RapidAPI BASIC $0 plan in marketplace metadata. **Not live-tested.** Vendor marketing still titles that column “Free Trial.” Do not make this the production rankings source until a subscribed key proves a non-expiring plan and a real ATP table.

### 3.5 Official ATP website

Reconfirmed:

- There is still no hobby `api.atptour.com`. **Repo-observed / unchanged.**
- `edx.atptour.com/en/rankings/singles` returned **HTTP 200 HTML** (~600 KB) containing player names. **Observed this spike.** That is a website page, not a JSON API. Parsing it would be HTML scraping. `www.atptour.com` ajax paths remain robots-disallowed. **Do not use.**

### 3.6 Official ranking cadence (product implication)

**Documented:**

- Wikipedia: “The ATP and WTA rankings are updated weekly on Mondays (UTC) or at the conclusion of a two-week tournament.”
- ATP live-rankings FAQ (edx / atptour): official PIF ATP Rankings are calculated Sunday night / published for the new week; live rankings are an unofficial in-week predictor.

**Inference:** a daily ATP *rankings* video has new official information about once a week. WTA can justify a daily video because `api.wtatennis.com` supplies yesterday’s matches and draw status for free. ATP cannot, at $0, after this spike.

---

## 4. Free Match Findings

Goal: yesterday’s completed ATP matches involving the Top 10, at $0.

### 4.1 Paid walls on the APIs that would otherwise work

| Vendor | Yesterday’s completed matches | Class |
| --- | --- | --- |
| BALLDONTLIE | `/atp/v1/matches` “Requires ALL-STAR tier” | **PAID** $9.99 **Documented** |
| LiveTennisAPI | `/history/matches` and `status=completed` | **PAID** BASIC **Documented** |
| api-tennis.com | `get_fixtures` date window | **PAID** **Documented** |

BALLDONTLIE additionally has **no `date=` query** on matches. Even on a paid key, yesterday would be a client-side `scheduled_time` filter. That is a product detail, not a reason to pay.

### 4.2 tennis-api.com — most interesting unvalidated $0 API

**Docs retrieved:** [docs.tennis-api.com](https://docs.tennis-api.com/), [pricing](https://tennis-api.com/api-pricing/), [coverage](https://tennis-api.com/api-coverage/), RapidAPI listing HTML for `tennis-api-atp-wta-itf` (22 Aug 2026).

**Documented capabilities (flagship `/tennis/v2/`):** fixtures by date and date range, player fixtures, rankings, tournaments, **draws** (`/tennis/v2/tournament/{tour_type}/{tournament}/{year}/draws`). Auth: `X-RapidAPI-Key` + host header.

**Observed RapidAPI plan JSON** (public BASIC plan on the flagship product):

| Field | Value |
| --- | --- |
| name | BASIC |
| visibility | PUBLIC |
| price | 0 |
| pricing | FREE |
| Requests | 50 / day, **hard** limit |
| Rate | 4 / second |

Paid plans on the same listing: PRO $29, ULTRA $59, MEGA $99.

**Vendor coverage page** still titles the $0 column **“Free Trial”** (50/day, hard limit). **Documented.** That is the opposite label of RapidAPI’s `pricing: FREE`.

**Inference, not fact:** RapidAPI BASIC $0 with a hard daily cap is usually a permanent freemium SKU, not a 14-day clock. The vendor’s own “Free Trial” heading means we must not treat it as proven-permanent until someone actually subscribes and reads the plan terms in the RapidAPI dashboard.

**Not done:** creating a RapidAPI account or calling any tennis-api endpoint. RapidAPI’s own pricing FAQ asks why a card is required for freemium APIs — card-on-file **Unknown**.

**If** BASIC is permanent and rankings + date fixtures work, 2 calls/day fits the 50/day cap and could support a limited daily ATP video. That remains a **validation task**, not the recommended v1 architecture.

Draws are the unique documented hobby feature. They are useless to us until the $0 plan is confirmed and a live draw payload is inspected.

### 4.3 TennisMyLife — best observed $0 match *file*, with serious caveats

**Site:** [stats.tennismylife.org/tennis-match-database](https://stats.tennismylife.org/tennis-match-database). The page documents CSV downloads and even pastes `curl` commands.

**Observed this spike:**

| Resource | robots.txt | Result |
| --- | --- | --- |
| `/robots.txt` | — | `Allow: /` and **`Disallow: /api/`** **Observed** |
| `/api/data-files` | Disallowed for crawlers | HTTP 200 JSON; 171 files. Documented by the site as the download index. **Do not use in an unattended crawler** |
| `/api/matches/latest` | Disallowed | HTTP 200 JSON, 10 latest matches, **including 22 Aug Cincinnati SF** Fils d. Cobolli 6-3 6-4. Has a real `tourney_date` timestamp. **Do not automate against `/api/`** |
| `/data/2026.csv` | Allowed (`Allow: /`) | HTTP 200 CSV, 1990 rows. Latest `tourney_date` **20260814** (Canada Masters final). **No Cincinnati.** File `mtime` in the index: 14 Aug 2026 |
| `/data/ongoing_tourneys.csv` | Allowed | HTTP 200 CSV, 92 Cincinnati matches through **QF**. `Last-Modified: Sat, 22 Aug 2026 03:18:40 GMT`. Columns include winner/loser names, ATP-style IDs, score, round, surface. **No per-match calendar date** — `tourney_date` is the week start `20260814` |
| `/data/ATP_Database.csv` | Allowed | 12,899 players. Sinner=`S0AG`, Alcaraz=`A0E2`, Cobolli=`C0E9` |

**Freshness, measured 22 Aug 2026 ~22:32 UTC:**

- Marketing copy: “updated daily, and ideally in real-time.” **Documented** on the page.
- Year file: **8 days behind** (stops at 14 Aug). **Observed.**
- Ongoing file: current event, through QF, missing the same-day SF that `/api/matches/latest` already had. **Observed.**
- GitHub mirror `Tennismylife/TML-Database`: last commit **27 Jan 2026**; `2026.csv` there only reaches 17 Jan. **Observed.** The GitHub repo is historical, not the live product.

**Why this is not ATP v1:**

1. The robots-allowed file has **no match calendar date**, so we cannot truthfully say “yesterday” without extra inference.
2. A snapshot-diff could say “new completed matches since last run,” which is honest, but that is a later experiment.
3. License text conflicts: the public page schema says MIT / `isAccessibleForFree`; the GitHub database README still says data usage is non-commercial unless permitted, and that the corpus was re-scraped from ATP. **Do not treat this as a clean production license.**
4. One-person hobby operations. Fine for research; risky as the only daily dependency.

**Useful later:** if legal/license is accepted, `ongoing_tourneys.csv` plus a ten-row ATP-ID map could add “results from this week’s event” to a weekly show, without claiming yesterday.

### 4.4 “Did this Top 10 player play yesterday?” vs “all ATP matches yesterday”

Narrowing to ten players does **not** unlock a new free API. Every structured API that can answer the per-player question for completed matches still gates that surface behind a paid tier (BALLDONTLIE, LiveTennisAPI, api-tennis).

The only $0 per-player answers we actually observed were:

- TennisMyLife latest/ongoing files (date or robots problems above)
- Wikipedia tournament wikitext (editor lag, brittle tables, different page per event)

### 4.5 Other free APIs / feeds

Investigated at documentation level; none became a v1 source:

- **RSS/JSON official ATP results feed:** not found.
- **TheSportsDB / generic sports APIs:** no evidence of current ATP Top 10 + yesterday singles at a permanent $0 tier sufficient for this job.
- **ESPN / Sofascore / Flashscore unofficial JSON:** not a supported API; typically ToS-restricted. Out of scope.
- **LiveTennisAPI FREE live board:** could describe matches *while they are on court*, not a next-morning completed recap.

---

## 5. Open Dataset Findings

### 5.1 Jeff Sackmann / Tennis Abstract `tennis_atp`

**Documented license:** CC BY-NC-SA 4.0 — attribution required, **non-commercial only**. Already rejected in the README for a potentially monetized YouTube pipeline. Unchanged.

**Freshness:**

- Public web search still lists [JeffSackmann/tennis_atp](https://github.com/JeffSackmann/tennis_atp) with a last push in May 2026 and 2026 season files.
- **Observed from this environment:** `https://github.com/JeffSackmann/tennis_atp` and raw `atp_matches_2026.csv` returned **HTTP 404**. GitHub API: `{status: 404}`. We could not re-download the live repo here.
- A third-party fetch of the 2026 CSV (via search-result cache) showed January United Cup / Brisbane through February Davis Cup rows in the tail of that cached view. Community notes (June 2026) said Sackmann had uploaded 2025–2026 through **end of May**. That is weeks-to-months lag, not next-morning.

**Verdict:** excellent historical research data. **Not** a daily product source. License is also the wrong shape if the channel earns ad revenue.

### 5.2 TennisMyLife datasets

Covered in §4.3. Summary:

| File | Freshness on 22 Aug 2026 | Daily video? |
| --- | --- | --- |
| GitHub `2026.csv` | January 2026 | No |
| Site `/data/2026.csv` | through 14 Aug 2026 | No (week-behind during Cincinnati) |
| Site `/data/ongoing_tourneys.csv` | same-week event, hours lag | Partial, no match date |
| Claimed “real-time” | Marketing | Not matched by the year file |

A weekly-updated research dump is useful. A file that misses the current Masters until it ends is not a daily video feed.

### 5.3 Could the Pi fetch a small file each morning?

Yes, technically: `GET https://stats.tennismylife.org/data/ongoing_tourneys.csv` is a ~20 KB robots-allowed public file. **Observed.**

Would yesterday’s results reliably be there by a morning reporting time? **Not reliably.** The 03:18 UTC upload on 22 Aug had QFs but not the later SF already visible on the (robots-disallowed) latest-matches API. Late North-American sessions can miss the same-morning file.

---

## 6. Tournament / Public Feed Findings

### 6.1 No common public structured feed we should automate

ATP tournament sites (Cincinnati Open WordPress `robots.txt` observed: `User-agent: *` / `Disallow:` empty, crawl-delay 10) are marketing sites. They do not expose one shared, documented JSON results API for hobby use.

The common technology underneath official scoring remains the **Infosys ATP platform**. **Documented** as ATP’s digital partner. Historical unofficial writeups describe encrypted `itp-atp-sls.infosys-platforms.com` responses. Previous spike received 403s. **Do not reverse-engineer.**

Sportradar is the official commercial ATP data licensee ([Official ATP Addendum](https://sportradar.com/official-atp-addendum/)). That is the licensed path, not a $0 path.

### 6.2 edx.atptour.com HTML

Reachable without Cloudflare challenge **Observed**. Still HTML, still unofficial as an API, still the wrong reliability class for an unattended Pi job. Out of architecture.

### 6.3 Wikipedia tournament articles

Pages such as “2026 Cincinnati Open – Men's singles” are updated by editors and can include completed-match wikitext. That is official MediaWiki access, not a Cloudflare bypass. It is still **per-event, format-fragile, and not a morning SLA**. Do not build ATP v1 on it.

---

## 7. Identity Strategy

We only need the Top 10. Over-engineering identity resolution is unnecessary.

### 7.1 Recommended v1 (single source)

BALLDONTLIE rankings own `PlayerRanking.player_id = str(player.id)`. No match provider in v1, so no crosswalk.

Wikipedia fallback: `player_id =` Wikipedia article title (`Jannik Sinner`) or a short stable slug. Movement still comes from our snapshot store keyed by that id.

### 7.2 If matches are added later

A **hand-maintained YAML of ~10–15 players** is preferable to fuzzy name matching:

```yaml
# illustration only — not implemented
Carlos Alcaraz:
  wikipedia: Carlos Alcaraz
  balldontlie_id: 1          # example; confirm against a live key
  tml_id: A0E2               # Observed in ATP_Database.csv
```

Why this is safe enough:

- The Top 10 changes slowly.
- Accented names (Auger-Aliassime, de Minaur) already cause trouble in this repo when matching across vendors.
- An explicit map fails visibly when a new #10 appears, instead of silently attaching the wrong player.

Name-only equality, lowercased, is acceptable as a *bootstrap* for filling that table once. It is not acceptable as the weekly join.

Do not write TennisMyLife or Wikipedia ids into the BALLDONTLIE `player_id` field if both exist. Rankings own the snapshot key.

---

## 8. Recommended ATP Product

**Name:** ATP Top 10 Rankings Update

**ATP v1 contents:**

1. Official-looking Top 10 (rank + name + country if present)
2. Ranking points
3. Movement vs the previous stored snapshot (and vendor movement if present)
4. Ranking-list date when the provider supplies one; otherwise omit the date rather than using “today”
5. TourProfile ATP branding already on `main` (titles/pronouns). No WTA copy.

**ATP v1 must not contain:**

- Fabricated “yesterday” results
- Elimination / champion / points earned / previous year
- Featured-player deep dives
- Any paid provider (api-tennis, LiveTennisAPI BASIC/PRO, BALLDONTLIE ALL-STAR)

**Optional later, not v1:** “Results from the current tournament week” from a license-cleared TennisMyLife ongoing CSV snapshot-diff, narrated as this week’s completed matches, never as yesterday unless a real match date exists.

No `data/atp_points_table.yaml` until tournament-status exists. Rankings points on the leaderboard come from the rankings provider, not from recomputation.

---

## 9. Recommended Cadence

**Weekly, after the official list publishes.**

Practical schedule:

```text
Monday evening or Tuesday morning
    → fetch BALLDONTLIE rankings
    → if ranking_date == last week's date, skip publish (same official list)
    → else render / narrate / (later) upload
```

Do **not** run every morning simply because WTA does.

Hybrid evaluated and **rejected for v1**:

```text
Daily when free match data exists
+ Weekly ranking update
```

Reason: the only observed $0 match file cannot date “yesterday,” and the only $0 match *API* that might do date queries (tennis-api BASIC) is unvalidated and vendor-labeled as a trial. A hybrid cadence would train viewers to expect daily results we cannot guarantee.

If tennis-api BASIC is later proven permanent and date-accurate, revisit a **tournament-week daily** or **results-on-days-with-Top-10-matches** show as a separate product decision. That is not this PR.

---

## 10. Operational Risks

| Risk | Likelihood / impact | Mitigation |
| --- | --- | --- |
| BALLDONTLIE free rankings quality unknown (no key here) | Medium until first live pull | First implementation PR uses offline fixtures; owner creates a free key and we compare Top 10 to Wikipedia / edx HTML before any YouTube publish |
| BALLDONTLIE changes the free column or shuts ATP | Low–medium; small vendor | Wikipedia fallback already validated |
| Wikipedia editors lag or leave a stale `as-of` | Already observed | Prefer BALLDONTLIE `ranking_date`; if using Wikipedia, print their `as-of`, never “today” |
| Official list does not change on a quiet Monday | Normal | Skip upload when `ranking_date` is unchanged |
| Temptation to “just add api-tennis” from PR #19 | Process | Close #19; keep WTA `api_tennis` untouched and WTA-only |
| TennisMyLife file format / hosting change | High if we depended on it daily | Do not depend on it in v1 |
| License conflict on TML / Sackmann NC | Legal | Do not ship those sources in a monetized pipeline without an explicit owner decision |
| YouTube / ATP trademark | Same gray area as WTA aggregators | Do not claim official ATP partnership; BALLDONTLIE terms forbid implying official status |
| Free-tier key leaked | Low | Env var, same pattern as other keys; 5 req/min is not a scrape budget |

Babysitting estimate for the recommended v1: **low**. One HTTP GET per week to a documented JSON endpoint, plus the snapshot store this app already has.

---

## 11. PR #19 Recommendation

PR #19 implements paid api-tennis.com ATP rankings and match plugins. It is **not merged**. It must **not** be merged under the $0 constraint.

**Recommendation: close PR #19 and start a new implementation PR.**

| Option | Recommendation |
| --- | --- |
| Modify #19 in place to swap api-tennis for BALLDONTLIE | **No.** The PR is shaped around `ApiTennisClient`, `event_type=ATP`, `event_type_key=265`, and a daily match path. That is the wrong product. |
| Merge #19 then disable billing | **No.** It encodes a paid architecture. |
| Preserve generic pieces in a new PR | **Yes, by copying ideas, not by merging the branch.** Useful ideas already on `main` or worth re-implementing: isolated `data/atp` + `output/atp` example config; ATP plugins as *new* files; leave WTA `api_tennis` alone; no tournament-status in v1; `ranking_date` left `None` unless the vendor supplies it. `supports_tournament_status` is **not** on `main`’s `TourProfile` — only mention it if a later PR needs that flag. |
| Abandon ATP entirely | **No.** A weekly free rankings video is worthwhile. |

Do not merge PR #19. Do not modify `main` in this research PR beyond adding this document.

---

## 12. Next Implementation PR

**Exactly one next engineering step:**

> Add a new ATP-only BALLDONTLIE rankings provider on the free `/atp/v1/rankings` endpoint, map into existing `PlayerRanking` (including `ranking_date` when present), and ship `config/config.atp.example.yaml` pointing at that provider with a separate `data_dir` / `output_dir`. Do not add a match provider. Do not schedule cron. Do not publish to YouTube. Do not modify WTA providers, narration, or points tables. Do not merge or rebase PR #19.

Suggested shape (still not this spike):

- `wta_daily/plugins/rankings/balldontlie_atp.py` (name TBD)
- Offline fixture from the vendor’s documented rankings JSON shape
- Tests: Top N mapping; missing key fails visibly; ATP + this provider is allowed; ATP + `wta_official` / `api_tennis` remains rejected
- README note: free BALLDONTLIE account required; matches are out of scope
- Optional follow-up (not in that PR): Wikipedia rankings fallback if the owner does not want a third-party key

**Stop after that provider PR.** Live key validation and a first weekly render are a later session.

---

## Appendix A — Outcome choice

| Outcome | Chosen? | Why |
| --- | --- | --- |
| A — Free ATP daily is practical | No | No fully validated $0 yesterday-dated match API |
| B — Free ATP daily is practical but limited | No | Closest unvalidated path is tennis-api BASIC (vendor-labeled trial) plus TML files that cannot say “yesterday” |
| **C — Free weekly ATP is better** | **Yes** | Official rankings are weekly; BALLDONTLIE free rankings look sufficient; a weekly show is truthful |
| D — No reliable free ATP product | No | Weekly Top 10 + points + movement is useful YouTube content |

---

## Appendix B — What changed versus PR #18

| PR #18 (merged) | This spike |
| --- | --- |
| Question: can we approximate WTA quality? | Question: what is useful at $0? |
| Recommendation: api-tennis.com paid, daily rankings + matches | Recommendation: BALLDONTLIE free, weekly rankings only |
| BALLDONTLIE as cheap backup if paying | BALLDONTLIE as the primary free rankings source |
| LiveTennisAPI FREE 1,000/day | OpenAPI 1.7.1 now says FREE **100/day** |
| tennis-api.com deferred until after v1 | Revisited; RapidAPI BASIC is $0 in marketplace JSON but vendor says “Free Trial”; still not v1 |
| Split providers rejected because of IDs | Split is acceptable at Top 10 with an explicit map; still unused in v1 |
| PR #19 then implemented the paid path | Close #19 |

---

## Appendix C — Sources cited

- https://atp.balldontlie.io/
- https://www.balldontlie.io/openapi/atp.yml
- https://balldontlie.io/terms.html
- https://app.balldontlie.io/
- https://en.wikipedia.org/wiki/Current_tennis_rankings
- https://en.wikipedia.org/wiki/Module:ATP_rankings/data/singles.json
- https://en.wikipedia.org/w/api.php
- https://www.mediawiki.org/wiki/API:Etiquette
- https://edx.atptour.com/en/rankings/singles
- https://edx.atptour.com/en/rankings/rankings-faq/live
- https://livetennisapi.com/
- https://docs.livetennisapi.com/reference.html
- https://raw.githubusercontent.com/livetennisapi/openapi/main/openapi.yaml (v1.7.1)
- https://tennis-api.com/api-pricing/
- https://tennis-api.com/api-coverage/
- https://docs.tennis-api.com/
- https://rapidapi.com/jjrm365-kIFr3Nx_odV/api/tennis-api-atp-wta-itf/pricing
- https://stats.tennismylife.org/tennis-match-database
- https://stats.tennismylife.org/robots.txt
- https://stats.tennismylife.org/data/2026.csv
- https://stats.tennismylife.org/data/ongoing_tourneys.csv
- https://github.com/Tennismylife/TML-Database
- https://github.com/JeffSackmann/tennis_atp (documented; 404 from this environment)
- https://api-tennis.com/ (paid; excluded)
- https://sportradar.com/official-atp-addendum/
- Repository: `wta_daily/models.py`, `wta_daily/tour.py`, `docs/atp-data-source-spike.md`, `docs/atp-support-audit.md`
