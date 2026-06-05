# Madrid Apartment Search — Handoff Notes

## What this project is
Automated apartment search for Koen: furnished 1-person apartment in Madrid,
August–December 2026, ≤€1000/month, ≤45 min commute to IE Tower (Begoña, Line 10).
Sources: HousingAnywhere, Spotahome, Idealista, Fotocasa.

## Infrastructure (all live)
| Service | URL / Location | Notes |
|---|---|---|
| Dashboard | https://madrid-dashboard.onrender.com | Live, public |
| Database | https://dunuilfxwivchtictnir.supabase.co | Project: madrid-appartment |
| Scraper | GitHub Actions, every 4h | `.github/workflows/scrape.yml` |
| Repo | https://github.com/koen-meier/madrid-appartment-search | branch: main |

## Credentials (all stored, do not re-enter)
- `.env` file at project root has all keys
- GitHub Actions secrets set: SUPABASE_URL, SUPABASE_SERVICE_KEY, APIFY_TOKEN
- Supabase anon key is hardcoded in `dashboard/index.html`
- GitHub token: `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` (repo + workflow scopes)

## Current scraper status (as of latest run)
| Source | Status | Notes |
|---|---|---|
| **Spotahome** | ✅ Partially working | Hits GraphQL at `/marketplace/graphql`, captures 4 responses but `_extract_items()` doesn't parse GraphQL format yet. 2 listings saved so far. |
| **HousingAnywhere** | ❌ 0 results | Network interception captures 0 JSON — page may use SSR or all API calls are filtered out. Debug logging added to next run. |
| **Idealista** | ❌ 0 results | Playwright loads page but gets 0 DOM cards — likely captcha/bot detection. Apify actor `lukass~idealista-scraper` also returns 0. |
| **Fotocasa** | ❌ 0 results | DOM selectors don't match. Cookie consent may still be blocking. |

## What the next chat needs to do

### Priority 1 — Fix Spotahome GraphQL parser
The scraper captures responses from `https://www.spotahome.com/marketplace/graphql`.
GraphQL responses have this shape:
```json
{"data": {"someQuery": {"homes": [...], "edges": [...]}}}
```
The current `_extract_items()` in `scrapers/spotahome.py` doesn't handle this.
**Fix**: read the debug log from the latest run to see the actual GraphQL response
structure, then update `_extract_items()` to navigate `data → * → homes/nodes/edges`.

To get the logs from the latest run:
```bash
TOKEN=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
RUN_ID=$(curl -s "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/runs?per_page=1" \
  -H "Authorization: token $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['workflow_runs'][0]['id'])")
JOB_ID=$(curl -s "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/runs/$RUN_ID/jobs" \
  -H "Authorization: token $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['jobs'][0]['id'])")
curl -sL "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/jobs/$JOB_ID/logs" \
  -H "Authorization: token $TOKEN" | grep -E "(response from|captured|NEW |Total)" | head -40
```

### Priority 2 — Fix HousingAnywhere
Debug log in next run will show what JSON responses (if any) are captured.
If still 0, try:
- Intercepting ALL responses (not just JSON) and log all URLs
- Or try fetching `https://housinganywhere.com/api/search` directly with httpx
- Their search page URL: `https://housinganywhere.com/s/Madrid--Spain/furnished-apartments`

### Priority 3 — Fix Idealista
Page gets 0 DOM cards — Idealista likely detects headless Chromium.
Options to try:
- Add `--disable-blink-features=AutomationControlled` launch arg to Playwright
- Use stealth mode: `pip install playwright-stealth`
- Or use the Apify actor `parseforge/idealista-scraper` (different from `lukass`)
- Idealista search URL: `https://www.idealista.com/alquiler-viviendas/madrid-madrid/con-precio-hasta_1000,amueblado/`

### Priority 4 — Fix Fotocasa
Similar anti-bot issues. Try same stealth approach as Idealista.
URL: `https://www.fotocasa.es/es/alquiler/viviendas/madrid-capital/todas-las-zonas/l?maxPrice=1000`

## To push and trigger a run
```bash
cd /Users/koenmeier/Developer/projects/madrid-appartment-search
git add -A && git commit -m "message" && \
git push https://koen-meier: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@github.com/koen-meier/madrid-appartment-search.git main

# Trigger run manually:
curl -X POST -H "Authorization: token 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" \
  -H "Content-Type: application/json" \
  "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/workflows/scrape.yml/dispatches" \
  -d '{"ref":"main"}'
```

## DB check (count listings)
```bash
curl -s "https://dunuilfxwivchtictnir.supabase.co/rest/v1/listings?select=source,price_eur,neighborhood&limit=10" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR1bnVpbGZ4d2l2Y2h0aWN0bmlyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA1MzI0NjgsImV4cCI6MjA5NjEwODQ2OH0.d5s3snjBVqetDkYNT6m1j_Q90-x5DukyK-fHQrppx50"
```

## File structure
```
madrid-appartment-search/
├── scrapers/
│   ├── base.py           — Listing dataclass, TARGET_NEIGHBORHOODS, httpx client
│   ├── housinganywhere.py — Playwright + network interception (needs fix)
│   ├── idealista.py      — Playwright DOM scrape (needs stealth fix)
│   ├── spotahome.py      — Playwright + GraphQL interception (needs parser fix)
│   └── fotocasa.py       — Playwright DOM scrape (needs fix)
├── db.py                 — Supabase REST upsert helpers
├── notifier.py           — Resend email (disabled, no key set)
├── run.py                — Main entry point
├── dashboard/index.html  — Single-page dashboard (live on Render)
├── schema.sql            — Already applied to Supabase
├── .env                  — All credentials (not in git)
├── .github/workflows/scrape.yml — GitHub Actions cron (every 4h)
└── render.yaml           — Render static site config
```
