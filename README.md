日本語版: [README_JP.md](README_JP.md)

# Career compass

A Streamlit MVP for personal job tracking, live job discovery, market snapshots, SMS digests, and evidence-linked career guidance.

## Run locally

```powershell
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

The app keeps the public Arbeitnow and Remotive feeds and also supports Adzuna, public Greenhouse boards, public Lever sites, and USAJOBS when configured. Results are normalized into one schema and are not a complete representation of the labor market.

## Job-source configuration

Arbeitnow and Remotive work without configuration. Enable optional sources with environment variables:

```powershell
$env:ADZUNA_APP_ID="your-app-id"
$env:ADZUNA_APP_KEY="your-app-key"
$env:GREENHOUSE_BOARDS="company-one,company-two"
$env:LEVER_SITES="company-one,company-two"
$env:USAJOBS_API_KEY="your-api-key"
$env:USAJOBS_EMAIL="your-email"
streamlit run streamlit_app.py
```

For Greenhouse, use the token in `boards.greenhouse.io/<token>`; for Lever, use the site name in `jobs.lever.co/<site>`. Comma-separate multiple employers. Adzuna provides target-country endpoints for Singapore, the United States, and the United Kingdom. Japan and China are covered through configured Greenhouse/Lever employers and matching global-feed listings; comprehensive coverage will require a licensed regional provider.

Jobs can now be filtered by country, source, employment type, workplace type, recruitment status, recency, remote status, and posted-date range. Insights tracks observed listing counts by source and country for each snapshot. Existing databases are migrated automatically with the new tracking columns.

Filters are committed with an **Apply filters** button. The saved profile degree is also applied automatically using degree requirements inferred from listing titles/descriptions; listings that do not state a degree remain visible. Account entry distinguishes **Sign in** from **Create new account**, rejects duplicate usernames during creation, and restores the SQLite profile for returning usernames. Optional gender is stored in the local profile database and is not displayed in job results or the profile summary.

## Persistence and historical data

Profiles, subscriptions, and daily listing snapshots are stored in `career_tracker.db`. Each job search records a daily snapshot. Run `python daily_digest.py` every day to build history. A real 5–10-year view requires licensed historical job-posting data (for example Lightcast, Revelio Labs, LinkUp, or a government dataset) or imported archived snapshots; the app never fabricates earlier observations.

SQLite is appropriate locally and on a persistent server. Streamlit Community Cloud has an ephemeral filesystem, so migrate the application data in `career_data.py` and `auth.py` to Postgres/Supabase before public deployment.

## SMS setup

The worker uses Twilio. Set these environment variables (or GitHub Actions repository secrets):

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_FROM_NUMBER`

For a local MVP, schedule `python daily_digest.py` with Windows Task Scheduler while the computer is online. The included GitHub Actions workflow runs at 00:15 UTC, but GitHub-hosted runners do not preserve the local SQLite database; use it only after moving subscriptions and snapshots to a hosted database. Configure Twilio consent records, STOP handling, verified sender requirements, and applicable local messaging rules before launch.

## Production checklist

- Replace the local prototype authentication with a managed identity service for public deployment.
- Move SQLite to hosted Postgres/Supabase and apply row-level security.
- Add a licensed job data provider for broad geography and historical coverage.
- Add observability, API retry/backoff, deduplication, and source terms-of-service review.
- Add an LLM provider to the coach only after implementing safety, citations, cost limits, and privacy disclosure.


## To be confirmed
1. security
2. search keywords in the link
3. Are there other ways to do notification pushes without connecting phone numbers / email (sensitive personal info)
