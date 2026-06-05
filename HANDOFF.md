# Madrid Apartment Search — Handoff Notes

## What this project is
Automated apartment search for Koen: furnished 1-person apartment in Madrid,
August–December 2026, ≤€1000/month, ≤45 min commute to IE Tower (Begoña, Line 10).
Sources: HousingAnywhere ✅, Spotahome ✅, Idealista ⚠️, Fotocasa ❌ dropped.

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
- GitHub token: `YOUR_GITHUB_TOKEN` (repo + workflow scopes)

## Current scraper status
| Source | Status | Notes |
|---|---|---|
| **HousingAnywhere** | ✅ Working | httpx SSR parse, `window.__staticRouterHydrationData`. ~2 listings ≤€1000 per run. |
| **Spotahome** | ✅ Working | httpx SSR parse with dates in URL, CSS class `price__amount`. ~3 listings ≤€1000 per run (5 pages). |
| **Idealista** | ❌ Needs fix | DataDome bot blocks all IPs. Apify tried: `epctex` → 404, `dtrungtin` → 403, `lukass` → starts but FAILS immediately. See Priority 1. |
| **Fotocasa** | ❌ Dropped | User doesn't want it. |

## DB state
6 listings in DB: 4 Spotahome, 2 HousingAnywhere. All ≤€1000.

```bash
# Check DB
curl -s "https://dunuilfxwivchtictnir.supabase.co/rest/v1/listings?select=source,price_eur,neighborhood,title&limit=20" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR1bnVpbGZ4d2l2Y2h0aWN0bmlyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA1MzI0NjgsImV4cCI6MjA5NjEwODQ2OH0.d5s3snjBVqetDkYNT6m1j_Q90-x5DukyK-fHQrppx50"
```

## What the next chat needs to do

### Priority 1 — Fix Idealista (only task remaining)

**The problem**: DataDome bot protection blocks all datacenter IPs (httpx 403, Firefox blank page).
Apify is the only path. Three actors were tried:
- `epctex/idealista-scraper` → 404 (actor does not exist)
- `dtrungtin/idealista-scraper` → 403 (private/unauthorized)
- `lukass/idealista-scraper` → accepted (201), then immediately FAILED

**What to do**:

**Step 1 — Find a working actor**: Go to https://apify.com/store and search "idealista". The correct slug format for the API is `username~actorname` (tilde, not slash). Try:
- `lukass~idealista-scraper` — the one that starts but fails. Might need different input format.
- Search apify.com/store for newer/active idealista actors.

**Step 2 — Debug lukass failure**: The run starts (201) but fails immediately. Likely the input payload is wrong. Try running the actor manually on Apify.com with the web UI to see what input format it expects. The current input sent is:
```json
{
  "locationName": "Madrid",
  "operation": "rent",
  "propertyType": "homes",
  "maxPrice": 1000,
  "maxItems": 50
}
```
Check the actor's README on apify.com/lukass/idealista-scraper for correct input schema.

**Step 3 — Try running lukass with a startUrl instead**:
```json
{
  "startUrls": [{"url": "https://www.idealista.com/alquiler-viviendas/madrid-madrid/con-precio-hasta_1000,amueblado/"}],
  "maxItems": 50
}
```

**Step 4 — Alternative actors to try** (check if they exist on apify.com first):
- `natanielalmeida~idealista-scraper`
- `tri_angle~idealista-scraper`
- Search "idealista spain rent" on apify.com/store

**Editing the actor config**: `scrapers/idealista.py` — `ACTORS` list and the payload in `_run_actor()`. The `lukass` branch uses the generic payload. The API call is:
```bash
POST https://api.apify.com/v2/acts/lukass~idealista-scraper/runs?waitForFinish=120
Authorization: Bearer $APIFY_TOKEN
```

**Step 5 — Check APIFY_TOKEN has compute units**: Log in to apify.com and check the account has credits. If zero, the actor will fail immediately.

### Priority 2 (optional) — More Spotahome/HousingAnywhere listings
- Spotahome: add more pages (currently 5, try 10). URL: `/s/madrid/for-rent:apartments/page:{n}?checkIn=2026-08-01&checkOut=2026-12-31`
- HousingAnywhere: only gets first page (23 listings). Try URL with `&page=2` etc.

## To push and trigger a run
```bash
TOKEN=YOUR_GITHUB_TOKEN
cd /Users/koenmeier/Developer/projects/madrid-appartment-search
git add -A && git commit -m "message" && \
git push https://koen-meier:$TOKEN@github.com/koen-meier/madrid-appartment-search.git main
curl -X POST -H "Authorization: token $TOKEN" -H "Content-Type: application/json" \
  "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/workflows/scrape.yml/dispatches" \
  -d '{"ref":"main"}'
```

## How to get logs from latest run
```bash
TOKEN=YOUR_GITHUB_TOKEN
RUN_ID=$(curl -s "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/runs?per_page=1" \
  -H "Authorization: token $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['workflow_runs'][0]['id'])")
JOB_ID=$(curl -s "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/runs/$RUN_ID/jobs" \
  -H "Authorization: token $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['jobs'][0]['id'])")
curl -sL "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/jobs/$JOB_ID/logs" \
  -H "Authorization: token $TOKEN" | grep -E "(Idealista|listings|Total|ERROR|status=|SUCCEEDED|FAILED)" | head -40
```

## File structure
```
madrid-appartment-search/
├── scrapers/
│   ├── base.py              — Listing dataclass, TARGET_NEIGHBORHOODS
│   ├── housinganywhere.py   — httpx + window.__staticRouterHydrationData ✅
│   ├── idealista.py         — Apify actor runner (needs fix) ⚠️
│   ├── spotahome.py         — httpx HTML parse, CSS class price__amount ✅
│   └── fotocasa.py          — ignore (dropped)
├── db.py                    — Supabase REST upsert helpers
├── notifier.py              — Resend email (disabled, no key set)
├── run.py                   — Main entry point
├── dashboard/index.html     — Single-page dashboard (live on Render)
├── schema.sql               — Already applied to Supabase
├── .env                     — All credentials (not in git)
├── .claude/settings.json    — bypassPermissions: true (no permission prompts)
├── .github/workflows/scrape.yml — GitHub Actions cron every 4h, installs chromium+firefox
└── render.yaml              — Render static site config
```

## Key technical notes
- **HousingAnywhere**: `window.__staticRouterHydrationData = JSON.parse("...")` in HTML. JSON is double-escaped: do `.encode('utf-8').decode('unicode_escape')` then `json.loads()`. Listings at `loaderData['0-22']['listings']` — code searches all loaderData keys for one with `listings` key.
- **Spotahome**: SSR with dates in URL. CSS classes are hashed (`_price__amount_xprcq_204`) — matched with `re.compile(r"price__amount")`. Walk 12 parent nodes from price element to find `<a>`. Listing URL: `https://www.spotahome.com/madrid/for-rent:apartments/{id}`.
- **Accept-Encoding**: Never set this header manually in httpx. httpx handles decompression only when it sets the header itself. Setting it manually causes binary garbage response.
- **Apify API**: Actor slugs use tilde not slash: `lukass~idealista-scraper`. Start run with `POST /v2/acts/{slug}/runs?waitForFinish=120`. Poll `/v2/actor-runs/{id}` for status. Get results from `/v2/datasets/{defaultDatasetId}/items`.
