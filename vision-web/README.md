# Strikee Vision — Reconciliation Web App

Private dashboard (deploy on **Vercel**) that reconciles **what the cameras
tracked** (Strikee Vision → Turso) against **what got billed** (Strikee POS →
Supabase) to surface revenue leakage — games played but not billed.

- **Auth:** one shared username/password from env → signed httpOnly cookie.
- **Never crawled:** `robots.txt` disallows all, `X-Robots-Tag: noindex` on every
  response, plus the login wall. Not for SEO / AI crawlers / anything.
- **Read-only** against tracking + billing data (writes only the small
  camera↔table mapping config to Turso).

## What it shows
- **Dashboard** (`/`): per table per day — **games detected vs billed**, the gap
  (played > billed = potential leakage), in-use minutes, and billed revenue.
- **Setup** (`/setup`): map each camera table (Vision asset) → its Strikee
  facility. Do this once; reconciliation keys off it.

## Data sources
- **Turso** (tracking): `events` (game_start) → games detected; `sessions` →
  in-use minutes; `assets` → tables.
- **Supabase / Strikee** (billing): `game_sessions.number_of_games` (staff-entered
  → the leakage point) + `total_price`, per `facility_id` per `session_date`,
  for `shop_id` (snooker club = 36). Read via the service-role key, **server-side
  only**.

## Setup
```bash
cp .env.example .env.local     # fill in the values
npm install
npm run dev                    # http://localhost:3000
```

Env (see `.env.example`): `APP_USERNAME`, `APP_PASSWORD`, `AUTH_SECRET`,
`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `STRIKEE_SHOP_ID`.

## Deploy (Vercel)
1. Push to a new git repo, import into Vercel.
2. Add the env vars in the Vercel project settings (mark them for Production).
3. Deploy. Consider Vercel's **Deployment Protection** as an extra gate on top of
   the app login.

## Notes / not-yet
- **Gaming lounge**: add its `shop_id` when live (a second venue in the UI).
- **Audit view** (staff frame add/removes): pending Strikee's `activity_log`
  actually populating.
- **Pool table (4)**: out of scope for game tracking (snooker-only model); reconcile
  snooker tables only.
- Supabase reporting RPCs (`get_dashboard_totals`, `get_session_duration`, …) are
  available as a richer alternative to the direct `game_sessions` aggregate.
