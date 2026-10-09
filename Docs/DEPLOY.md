# Deploying Open-MES (Render + Supabase)

The app is a normal Django container. **Supabase** holds the PostgreSQL database; **Render** runs the web app. Nothing else is needed. All settings come from environment variables ([.env.example](../.env.example)), and the same code runs locally on SQLite with login off.

> Deploy from a **private** repository if the data you load is real: the image contains only code. Source workbooks (`data/`) are excluded by `.dockerignore`; real data goes into the database, not into the image.

## 1. Database: Supabase

1. Create a project. Pick the **London (eu-west-2)** region if your data is UK/EU, and set a strong database password.
2. **Switch off the Data API.** Project Settings > Data API > disable. Django talks to the database directly with the password, and Supabase otherwise publishes every table in the `public` schema over a REST API that does not know about this app's login.
3. Project Settings > Database > Connection string > **Transaction pooler** (port 6543). Use this one rather than the direct connection, which is IPv6-only. It looks like:
   `postgresql://postgres.<ref>:<password>@aws-0-eu-west-2.pooler.supabase.com:6543/postgres`
   Append `?sslmode=require`. This is your `DATABASE_URL`.
4. Backups: the free plan has none. For real use choose a plan with daily backups (and point-in-time recovery if you can), and do a **restore test** before relying on it.

## 2. Web app: Render

1. New > Blueprint, pick the repository. `render.yaml` defines the service (Docker, Frankfurt, health check `/healthz`, `DEBUG=0`, `MES_REQUIRE_LOGIN=1`, a generated `SECRET_KEY`).
2. When prompted, paste `DATABASE_URL`. Never commit it.
3. Deploy. On every start the container applies new migrations (`manage.py migrate`) and serves with gunicorn. Render supplies HTTPS and the hostname; it is allowed automatically.
4. Optional: add a custom domain in Render, then set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` (`https://your.domain`).

## 3. First users

Run these from your own machine against the production database (set `DATABASE_URL` in that shell first), or from the Render shell if your plan has one:

```
python manage.py createsuperuser                  # a full administrator (can also use /admin/)
python manage.py add_user alex --role technician --name "Alex Smith"
python manage.py add_user sam  --role planner --role team-leader
```

Roles: **Planner** (allocate and issue stock, assign, raise works orders, machine status), **Technician** (start, record units, retest, finish, log defects), **Team leader** (everything a technician and planner can do, plus QA approve and reject), **Admin**. Anyone signed in can look at everything. `add_user` prints a generated password once; ask people to change it. Every action is recorded in the work order history with the username.

## 4. Loading real data

`manage.py seed` is for demos and **refuses to run** against PostgreSQL or with `DEBUG` off unless you pass `--force`, because it wipes the database. Do not use it in production. Load real data with the importers (BOM workbooks, stock master, price list, test reports) run from a local checkout against the production `DATABASE_URL`; they update records instead of wiping them.

## 5. Checklist before real use

- `DEBUG=0`, `MES_REQUIRE_LOGIN=1`, a long random `SECRET_KEY` (the app refuses to start without one when `DEBUG=0`).
- Supabase Data API disabled; database password stored only in Render's environment.
- Backups enabled and a restore tested; know who can restore.
- `python manage.py check --deploy` is clean (the two HSTS notes are optional).
- Remember the trade-off: this is cloud-hosted, so if the internet drops at the factory, nobody can record work until it returns.

## Running it yourself instead

Any host that runs a Docker container works (`docker build -t open-mes .` then run with the same environment variables), including a PC at the factory. The database can stay on Supabase or be a local PostgreSQL; only `DATABASE_URL` changes.
