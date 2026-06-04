# Madrid Apartment Search

Automated search for a furnished 1-person apartment in Madrid (August–December),
≤€1000/month, ≤45 min commute to IE Tower (Begoña, Line 10).

Runs in the cloud — no laptop required. Checks every 4 hours and emails new matches.

## One-time setup (15–20 min)

### 1. Supabase (database + dashboard API)
1. Create a free project at https://supabase.com
2. Go to **SQL Editor** and run the contents of `schema.sql`
3. From **Settings > API** copy:
   - Project URL → `SUPABASE_URL`
   - `anon` public key → `SUPABASE_ANON_KEY`
   - `service_role` secret key → `SUPABASE_SERVICE_KEY`
4. Open `dashboard/index.html` and replace the two placeholder strings:
   - `%%SUPABASE_URL%%` → your project URL
   - `%%SUPABASE_ANON_KEY%%` → your anon key

### 2. Resend (email notifications)
1. Sign up at https://resend.com (free tier: 3,000 emails/month)
2. Verify a sending domain (or use their test domain for personal use)
3. Create an API key → `RESEND_API_KEY`
4. Set `EMAIL_FROM` and `EMAIL_TO`

### 3. Apify (Idealista scraping)
1. Sign up at https://apify.com (free $5/month credit — more than enough)
2. Go to **Settings > Integrations** → copy your API token → `APIFY_TOKEN`

### 4. Deploy to Render
1. Push this repo to GitHub
2. Go to https://render.com → **New > Blueprint** → connect your repo
3. Render reads `render.yaml` and creates both services automatically
4. In the **madrid-scraper** cron job, add the environment variables from `.env.example`

That's it. The scraper runs every 4 hours. New listings trigger an email and appear on the dashboard.

## Running locally (optional)
```bash
cp .env.example .env
# fill in .env values
pip install -r requirements.txt
python run.py
```

## Dashboard
Open the Render static URL (or `dashboard/index.html` locally after filling in credentials).

- **👍 / 🤔 / 👎** — rate a listing; add a comment to note why
- Ratings are stored in Supabase and used to refine filters over time
- **Hide thumbs down** — declutters the view once you've dismissed bad ones
- Filters: source, neighborhood, price cap, rating status

## Sources
| Source | Method | Coverage |
|---|---|---|
| HousingAnywhere | JSON API | Mid-term furnished, best fit |
| Idealista | Apify cloud actor | Largest Spanish portal |
| Spotahome | HTML scrape (`__NEXT_DATA__`) | Mid-term specialist |
| Fotocasa | JSON API + HTML fallback | Major Spanish portal |

## Adjusting criteria
Edit `scrapers/base.py` (`TARGET_NEIGHBORHOODS`) and the search URLs/params
in each scraper file. Re-deploy by pushing to GitHub — Render redeploys automatically.
