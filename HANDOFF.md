# Madrid Apartment Search — Handoff Notes

## What this project is
Automated apartment search for Koen: furnished 1-person apartment in Madrid,
August–December 2026, ≤€1200/month, ≤45 min commute to IE Tower (Begoña, Line 10).
Sources: HousingAnywhere ✅, Spotahome ✅, Idealista ✅, Fotocasa ❌ dropped.

## Infrastructure (all live)
| Service | URL / Location | Notes |
|---|---|---|
| Dashboard | https://koen-meier.github.io/madrid-appartment-search/ | GitHub Pages, instant deploys |
| Database | https://dunuilfxwivchtictnir.supabase.co | Project: madrid-appartment |
| Scraper | GitHub Actions, every 4h | `.github/workflows/scrape.yml` |
| Repo | https://github.com/koen-meier/madrid-appartment-search | branch: main, **public** |

## Credentials (all stored, do not re-enter)
- `.env` file at project root has all keys
- GitHub Actions secrets set: SUPABASE_URL, SUPABASE_SERVICE_KEY, APIFY_TOKEN
- Supabase anon key is hardcoded in `docs/index.html`
- GitHub token expires ~Sep 2026. If expired, generate new one at github.com/settings/tokens (repo + workflow scopes). **Do NOT hardcode the token in any file in the repo** — GitHub will auto-revoke it since the repo is public.

## Current scraper status
| Source | Status | Notes |
|---|---|---|
| **HousingAnywhere** | ✅ Working | httpx SSR parse, `window.__staticRouterHydrationData`. Includes lat/lng. |
| **Spotahome** | ✅ Working | httpx SSR parse + detail page fetch for lat/lng coords. |
| **Idealista** | ✅ Working | Apify actor `lukass~idealista-scraper`, residential proxy, includes lat/lng. |
| **Fotocasa** | ❌ Dropped | User doesn't want it. |

## DB state (as of Jun 5 2026)
40 listings: 18 Spotahome, 16 Idealista, 6 HousingAnywhere. All ≤€1200.

```bash
# Check DB
curl -s "https://dunuilfxwivchtictnir.supabase.co/rest/v1/listings?select=source,price_eur,neighborhood,title&limit=50" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR1bnVpbGZ4d2l2Y2h0aWN0bmlyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA1MzI0NjgsImV4cCI6MjA5NjEwODQ2OH0.d5s3snjBVqetDkYNT6m1j_Q90-x5DukyK-fHQrppx50"
```

## Dashboard features
- **Price filter** up to €1200
- **Location tags** auto-computed from lat/lng:
  - 🌸 pink — ≤25 min walk from Plaza de España (40.4237, -3.7124)
  - 🏢 blue — ≤15 min walk from IE Tower (40.4680, -3.6745)
- **Multi-user voting** — 👍 🤔 👎 with counts. Each visitor gets a persistent anonymous `voter_id` stored in localStorage. One vote per listing per person. Click again to remove. Votes stored in `ratings` table with `voter_id` column.
- Spotahome listings fetch coords from each listing's detail page — tags work for all sources.

## Supabase schema changes (already applied)
```sql
-- ratings table has voter_id column + unique constraint + delete policy
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS voter_id TEXT;
ALTER TABLE ratings ADD CONSTRAINT ratings_listing_id_voter_id_key UNIQUE (listing_id, voter_id);
CREATE POLICY "public delete ratings" ON ratings FOR DELETE USING (true);
```

## To push and trigger a run
```bash
TOKEN=YOUR_GITHUB_TOKEN
cd /Users/koenmeier/Developer/projects/madrid-appartment-search
git add -A && git commit -m "message" && \
git push https://koen-meier:$TOKEN@github.com/koen-meier/madrid-appartment-search.git main
# Trigger scraper manually:
curl -X POST -H "Authorization: token $TOKEN" -H "Content-Type: application/json" \
  "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/workflows/scrape.yml/dispatches" \
  -d '{"ref":"main"}'
```

## How to get logs from latest scraper run
```bash
TOKEN=YOUR_GITHUB_TOKEN
RUN_ID=$(curl -s "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/runs?per_page=5" \
  -H "Authorization: token $TOKEN" | python3 -c "import sys,json; runs=[r for r in json.load(sys.stdin)['workflow_runs'] if 'Scrape' in r['name']]; print(runs[0]['id'])")
JOB_ID=$(curl -s "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/runs/$RUN_ID/jobs" \
  -H "Authorization: token $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['jobs'][0]['id'])")
curl -sL "https://api.github.com/repos/koen-meier/madrid-appartment-search/actions/jobs/$JOB_ID/logs" \
  -H "Authorization: token $TOKEN" | grep -E "(NEW|listings|ERROR|SUCCEEDED|FAILED)" | head -50
```

## File structure
```
madrid-appartment-search/
├── scrapers/
│   ├── base.py              — Listing dataclass, TARGET_NEIGHBORHOODS
│   ├── housinganywhere.py   — httpx + window.__staticRouterHydrationData ✅
│   ├── idealista.py         — Apify actor runner (lukass, residential proxy) ✅
│   ├── spotahome.py         — httpx HTML parse + detail page coord fetch ✅
│   └── fotocasa.py          — ignore (dropped)
├── db.py                    — Supabase REST upsert (on_conflict=source,external_id)
├── notifier.py              — Resend email (disabled, no key set)
├── run.py                   — Main entry point
├── docs/index.html          — Single-page dashboard (GitHub Pages)
├── schema.sql               — Base schema (already applied; see above for extra migrations)
├── requirements.txt         — httpx, beautifulsoup4, lxml, playwright
├── .env                     — All credentials (not in git)
├── .claude/settings.json    — bypassPermissions: true
├── .claude/launch.json      — Preview server config (serves docs/ on port 3456)
├── .github/workflows/scrape.yml — GitHub Actions cron every 4h
└── render.yaml              — Render config (no longer used, GitHub Pages instead)
```

## Key technical notes
- **HousingAnywhere**: `window.__staticRouterHydrationData = JSON.parse("...")` in HTML. JSON is double-escaped. Listings at `loaderData['0-22']['listings']`.
- **Spotahome**: SSR with dates in URL. CSS classes are hashed — matched with `re.compile(r"price__amount")`. Coords extracted from detail page via regex `coord[\"]+,\[[^\]]+\],(lng),(lat)` (note: order is lng, lat).
- **Idealista**: Actor `lukass~idealista-scraper`. Input needs `country: "es"`, `operation: "rent"`, `district: "Madrid"`, `proxy: {useApifyProxy: true, apifyProxyGroups: ["RESIDENTIAL"]}`. Search URL cap is €1200.
- **Upsert**: db.py uses `POST /rest/v1/listings?on_conflict=source,external_id` with `Prefer: resolution=merge-duplicates` — existing listings get coords updated on each run.
- **Accept-Encoding**: Never set manually in httpx — causes binary garbage response.
- **GitHub Pages**: Deploying from `docs/` folder on `main` branch. Deploys automatically on every push, takes ~60s.
- **Render**: Still configured (render.yaml) but no longer used. Dashboard moved to GitHub Pages due to Render build failures (greenlet compile error on their infra).
- **Voter IDs**: Anonymous UUIDs stored in browser localStorage. One per browser. Votes stored in `ratings` with `voter_id` column. RLS allows SELECT, INSERT, DELETE (all public).

## Potential future improvements
- Add more Spotahome pages (currently 5, ~240 listings scraped, 18 pass ≤€1200 filter)
- Add HousingAnywhere page 2+ (currently only first page of 23 listings)
- Notify by email when new listings appear (Resend key not set — add RESEND_API_KEY secret)
- Add commute time filter (transit, not just walking)
- Geocode Spotahome listings that still return null coords (rate-limited or bot-blocked detail pages)
