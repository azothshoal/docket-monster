# Docket Monster

A weekly digest tool for journalists covering federal tech and privacy litigation at the Northern District of California (CAND). Scrapes 38 judge calendars, enriches case data from CourtListener, and delivers a curated HTML email digest of upcoming relevant hearings.

The name comes from the ethos: there are 38 judges and hundreds of cases scheduled every week. Gotta catch 'em all.

Built in collaboration with [Claude](https://claude.ai).

---

## What It Does

1. **Scrapes** all CAND judge calendar pages (38 judges) via Playwright/headless Chromium
2. **Parses** raw HTML into `(judge, location, courtroom, date, time, case_number)` rows → `schedule.csv`
3. **Enriches** each case via CourtListener API → `enriched.csv`
4. **Filters** for tech/privacy relevance → `relevant.csv`
5. **Emails** an HTML digest with both CSVs attached via Gmail SMTP

---

## Powered by CourtListener

Case enrichment is powered by the [CourtListener API](https://www.courtlistener.com/help/api/), a free, open legal research platform maintained by the [Free Law Project](https://free.law/). CourtListener provides authoritative, structured data — case names, nature-of-suit codes, causes of action, filing dates — directly from court records.

This is a deliberate design choice over using an LLM for enrichment: CourtListener data is exact, costs nothing to query, and carries no risk of hallucination. Case names and legal classifications are facts, not inferences. For a tool a journalist relies on, that matters.

CourtListener data is used in accordance with their [Terms of Service](https://www.courtlistener.com/terms/) for non-commercial journalistic purposes. The cache minimizes API load; results are never redistributed.

---

## Why CAND

The Northern District of California (San Francisco/San Jose/Oakland/Eureka) is the primary venue for tech and privacy litigation in the US — Apple, Google, Meta, and most major Silicon Valley companies are headquartered here, making it the default forum for antitrust, data privacy, CFAA, DMCA, and Section 230 cases. CAND publishes judge calendars publicly at [apps.cand.uscourts.gov](https://apps.cand.uscourts.gov/CEO/). This tool scrapes those pages directly; no PACER account required.

---

## Quick Start

```bash
cd "Projects/Docket Monster"
source .venv/bin/activate

# Full run (scrape + parse + enrich + email)
python run.py && python digest.py

# Skip scraping, use cached raw_html/ (faster for testing)
python run.py --no-scrape && python digest.py

# Parse only — no live requests
python run.py --dry-run

# Adjust windows
python run.py --days 21              # widen schedule/enriched window (default: 14)
python run.py --relevant-days 14     # widen digest window (default: 7)
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```
COURTLISTENER_TOKEN=your_token_here
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
RECIPIENT_EMAIL=recipient@example.com
```

- **CourtListener token**: Free account at [courtlistener.com](https://www.courtlistener.com/sign-in/). Without a token: 100 API requests/day. With free account: 5,000/day. The cache means most weekly runs use far fewer calls after the first run.
- **Gmail App Password**: Not your real Gmail password. Generate one at Google Account → Security → 2-Step Verification → App passwords. Requires 2FA to be enabled.

---

## Output Files

| File | Contents | Default window |
|------|---------|----------------|
| `schedule.csv` | All hearings: judge, location, courtroom, date, time, case_number | 14 days |
| `enriched.csv` | All hearings + CourtListener data (case name, NOS, cause, etc.) | 14 days |
| `relevant.csv` | Filtered digest — tech/privacy cases only | 7 days (coming week) |
| `courtlistener_cache.json` | Cached CourtListener results — known cases never re-queried | persistent |
| `raw_html/` | Per-judge cached HTML files + `index.json` metadata | persistent |

---

## Pipeline

```
[run.py]
    │
    ├─ Step 1: scraper.py ──────────────────────────────────────────────────────────────
    │    Fetches 38 CAND judge calendar pages (Playwright, headless Chromium)
    │    Saves: raw_html/{judge_slug}.html + raw_html/index.json
    │
    ├─ Step 2: parse.py ────────────────────────────────────────────────────────────────
    │    Reads raw_html/*.html
    │    Extracts (judge, location, courtroom, date, time, case_number)
    │    Filters to upcoming window (default: 14 days)
    │    Deduplicates (same case on multiple judge calendars)
    │    Writes: schedule.csv
    │
    └─ Step 3: enrich.py ───────────────────────────────────────────────────────────────
         Reads schedule.csv
         Queries CourtListener API for each unique case number (3 retries on failure)
         Caches results in courtlistener_cache.json
         Scores relevance (NOS codes + tech party keywords + cause keywords)
         Writes: enriched.csv (14-day window)
                 relevant.csv (7-day window — upcoming week only)
                 failed_lookups.txt (if any cases couldn't be enriched)

[digest.py]
    Reads relevant.csv (and failed_lookups.txt if present)
    Sends HTML email with table of relevant cases grouped by date
    Attaches relevant.csv and enriched.csv
    Flags any failed lookups in the email for manual review
```

---

## Relevance Filtering

Cases are flagged relevant if they match any of:

**1. Nature-of-suit codes** (narrow — tech/privacy specific only):

| Code | Category |
|------|---------|
| 480 | Consumer Credit / Data Breach |
| 895 | Freedom of Information Act |

**2. Named tech company in case name** (whole-word match to avoid substrings like "San Francisco"):

Google, Alphabet, Meta, Facebook, Instagram, Apple, Microsoft, Amazon, OpenAI, Anthropic, Nvidia, Twitter, X Corp, X.com, TikTok, ByteDance, Uber, Lyft, Airbnb, Salesforce, Oracle, Adobe, Netflix, Spotify, LinkedIn, Snap, Snapchat, Pinterest, Palantir, Cloudflare, YouTube, Zoom, Slack, Dropbox, DoorDash, Instacart, Stripe, PayPal, Coinbase, Robinhood, Tesla, SpaceX, Samsung, Intel, Qualcomm, Broadcom, WhatsApp, Threads, Roblox

**3. Cause keywords — two tiers:**

- **Strong** (trigger regardless of party): `privacy`, `data breach`, `wiretap`, `biometric`, `facial recognition`, `artificial intelligence`, `machine learning`, `surveillance`, `computer fraud`, `cfaa`, `dmca`, `section 230`, `california consumer`, `ccpa`, `gdpr`, `coppa`
- **Weak** (only trigger if a named tech company is already matched): `antitrust`, `monopol`, `sherman act`, `clayton act`, `copyright`, `patent`, `trade secret`

The weak tier catches IP/antitrust cases involving tech companies without flooding the digest with generic patent or copyright cases.

---

## Data Architecture

CAND calendars and CourtListener are complementary sources:

| Data | Source | Why |
|------|--------|-----|
| Assigned judge | CAND calendar | Only place this lives |
| Hearing date & time | CAND calendar | Only place this lives |
| Courtroom | CAND calendar | Only place this lives |
| Party names (clean) | CourtListener | Authoritative, no regex artifacts |
| Nature of suit code | CourtListener | Drives filtering |
| Case active/closed status | CourtListener | Authoritative |
| Cause of action | CourtListener | Authoritative |

The scraper extracts only `(judge, location, courtroom, date, time, case_number)`. Everything else comes from CourtListener.

---

## Two-Window Design

- **14-day window** → `schedule.csv` + `enriched.csv`: editor context on the next two weeks
- **7-day window** → `relevant.csv` + email digest: actionable cases for the coming week only

CourtListener is only queried for cases within the 14-day window. The cache handles repeat cases week over week.

---

## Automated Deployment (k3s)

The `k3s/` directory contains manifests for running Docket Monster as a weekly CronJob on a home server.

### Setup

1. Build the image for your server's architecture (likely `linux/amd64`):
   ```bash
   docker build --platform linux/amd64 -t docket-monster:latest .
   docker save docket-monster:latest -o docket-monster.tar
   scp docket-monster.tar yourserver:~/
   ```

2. Import into k3s on the server:
   ```bash
   sudo k3s ctr images import ~/docket-monster.tar
   ```

3. Create the secret — copy `k3s/secret.yaml`, fill in real values, apply, then delete the file:
   ```bash
   cp k3s/secret.yaml k3s/secret.local.yaml
   # edit k3s/secret.local.yaml with your real values
   sudo kubectl apply -f k3s/secret.local.yaml
   rm k3s/secret.local.yaml
   ```

4. Apply the remaining manifests:
   ```bash
   sudo kubectl apply -f k3s/pvc.yaml
   sudo kubectl apply -f k3s/cronjob.yaml
   ```

5. Test manually:
   ```bash
   sudo kubectl create job --from=cronjob/docket-monster test-run
   sudo kubectl logs -f $(sudo kubectl get pods --selector=job-name=test-run -o name)
   ```

The CronJob runs every Friday at 3pm in the server's local timezone (`0 15 * * 5`). Persistent data (cache, raw_html, CSVs) lives on a PVC mounted at `/data`.

**Note:** `k3s/secret.yaml` is a template with placeholder values and is safe to commit. Never create a version with real credentials that could be accidentally pushed.

---

## Dependencies

```
requests, beautifulsoup4, python-dotenv, playwright
```

Install: `pip install -r requirements.txt && playwright install chromium`

---

## Adapting to Other Beats

Docket Monster was built for CAND tech/privacy coverage but the architecture is generic. CourtListener covers all federal districts, so the enrichment pipeline (`enrich.py`, `digest.py`) works without modification. Some ways to fork it:

**Different district** — point `scraper.py` at your district's public calendar pages, update the `court` parameter in `enrich.py` to your district's CourtListener court ID (e.g. `"nysd"`, `"dcd"`), and adjust the relevance filters.

**Different beat** — the party keyword list and cause keywords in `enrich.py` are easy to swap out. Covering immigration? Environmental? Financial fraud? Change the lists and the NOS codes.

**No server needed** — the k3s deployment is optional. You can run the full pipeline locally with `python run.py && python digest.py` on any machine with Python and Chromium. A simple cron job on a Mac or Linux laptop works fine:
```
0 15 * * 5 cd /path/to/docket-monster && source .venv/bin/activate && python run.py && python digest.py
```

If your district publishes judge calendars publicly, the rest is just configuration.

---

## Not In Scope (v1)

- Tracking case history over time (would require a database)
- PACER document access (requires account + per-page fees)
- UI for customizing filters
