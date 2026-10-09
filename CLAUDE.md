# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Open-MES: an open-source Manufacturing Execution System layer (Django 5, SQLite, server-rendered templates, no login yet). Machine connectivity (PLC/SCADA/MQTT) is out of scope; events carry a `source` field as the hook for it. Plans: [Docs/Plans/PLAN.md](Docs/Plans/PLAN.md). Data-pack guide: [Docs/DATA-PACKS.md](Docs/DATA-PACKS.md).

## Commands

Python may not be on PATH; use the venv (`.venv/Scripts/python.exe`). Run from `app/`:

- `manage.py migrate`, `manage.py seed [--pack NAME]` (RESETS the database and loads a data pack), `manage.py runserver`
- `manage.py test mes` (all), `manage.py test mes.tests_bom.SomeTest.test_name` (single)
- `manage.py import_test_reports <workbook>`
- `MES_DB=<path>` points Django at a different SQLite file (used for parallel workers); `MES_DATA_PACK` and `MES_DATA_DIR` choose the default pack and where real workbooks live.

Repository family: this repo (open-mes-demo-static) is the static demo: the full application plus the static-site builder, published to GitHub Pages. `open-mes-demo-server` (its `upstream`) is the canonical runnable app: make application changes there first and merge them here with `git fetch upstream && git merge upstream/main`. Each repo's footer link comes from `MES_PROJECT_URL`.

## Architecture

- **One catalogue table.** `Product` holds finished products, assemblies and components (`kind`, `category`, `range_name`, `unit_cost`, `rrp`, stock and supplier fields). `BomLine` links any item to any other, so everything cross-references. `RoutingStep` gives build time and the machine each step needs. Nearly every model has `created_at`/`updated_at` (`TimeStamped`).
- **Derived figures are never stored.** `mes/costing.py` computes build time, BOM cost and total cost (BOM + build minutes x `MES_LABOUR_RATE_PER_HOUR`); `mes/bom.py` does explosions and where-used.
- **Work orders** follow entered → allocated → issued → in_progress → qa → complete; each step is its own POST view in `views.py` and writes an `Event` (append-only audit log) via `_log`. `Unit` is a serialised unit; first-pass yield counts a unit as first-pass only if it was never retested.
- **Feature areas** each live in their own files: `views_<area>.py`, `urls_<area>.py`, `templates/mes/<area>/`, `tests_<area>.py`. Areas: catalogue, bom, machines, planning, defects, data (a generic table browser). `mes/urls.py` includes each.
- **Tables:** every list uses `mes/tables.py` `build_table` with `templates/mes/_table.html` (search, sort, pagination, `?format=csv`). `context.py` supplies the alert count and breadcrumbs.
- **UI:** `base.html` is a sidebar shell with an inline SVG icon sprite and no external assets. The dashboard charts are hand-written SVG drawn by JS from `json_script` data built in `views.dashboard`.

## Production and access

Settings are environment-driven (`config/settings.py`, `.env.example`): `DATABASE_URL` (PostgreSQL, e.g. Supabase; otherwise SQLite), `DEBUG`, `SECRET_KEY` (required when `DEBUG=0`), `MES_REQUIRE_LOGIN`. Login is **off by default** so the demo and tests are open; with `MES_REQUIRE_LOGIN=1` the `LoginRequired` middleware sends anonymous visitors to `/login/` and POST actions are gated by role. Roles are Django groups created by migration 0013 (Planner, Technician, Team leader, Admin); `mes/permissions.py` maps each action (`stock`, `assign`, `work`, `qa`, `raise`, `machine`) to roles and `@require_role` guards the views; the `can.*` template variables hide buttons a role cannot use. `Event.actor` records the username through a context variable set by the `AuditUser` middleware. `seed` refuses to wipe a non-SQLite or `DEBUG=0` database without `--force`. Deployment (Docker, Render, Supabase): [Docs/DEPLOY.md](Docs/DEPLOY.md). To test against real PostgreSQL locally, `pip install pgserver` (embedded server; on Windows copy the `tzdata` zoneinfo folder into its `share/postgresql/timezone`).

## Data packs

The software is generic; datasets are **packs** in `app/mes/datapacks/` (plain-data modules, see `generic.py` and the contract in `datapacks/__init__.py`). `seed` validates the pack (`check_pack`), builds the catalogue (`mes/demo/builder.py`), creates the demo activity the pack asks for, runs the pack's optional `load_real_data(command)`, then classifies items from BOM structure (`mes/classify.py`) and works out costs. The `mes/demo/<area>.py` hooks read their inputs from `ctx.pack`, so they contain no business data.

Importers: `mes/bom_import.py` (BOM explosion sheets, flat design BOMs, stock master), `mes/pricing.py` (price list, RRP-based cost calibration), `mes/importers.py` (test-report workbooks). They match sheets by header row and ignore unknown sheets.

## Static demo

`manage.py build_static_site` renders the whole app as a read-only static site (GitHub Pages) from the database, with `MES_STATIC_EXPORT` on: `_table.html` and `base.html` switch to a client-side mode, `mes/static_site/demo.js` does search, sort, CSV export and form navigation in the browser, and POST actions show a read-only notice. `scripts/build_static_site.py` builds it from the generic pack with a throwaway DB. `tests_static_site.py` builds the full site and fails on any broken link. When you add a GET form or a table, check it still works in static mode. Notes: [Docs/STATIC-DEMO.md](Docs/STATIC-DEMO.md).

## Conventions

- Keep the public tree free of real business data: product codes, staff names, customers, prices and source workbooks belong in private packs and git-ignored `data/` folders. `tests_datapacks.py` checks the generic pack stays clean.
- Add a test for each new behaviour; the generic-pack seed test renders every page, so a broken template fails the suite.
- No lint config or CI yet.
