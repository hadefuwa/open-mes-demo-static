# Open-MES

**Open-MES** is an open-source Manufacturing Execution System (MES) layer for discrete manufacturers. It tracks work orders from entry to completion, serialised units and their test results, bills of materials and cost to manufacture, machines and routings, planning, and defects, with every record linked to every other and every table exportable to CSV.

It runs out of the box on **dummy data** for an invented training-equipment maker, so you can click through every feature straight after cloning.

**Live demo:** https://hadefuwa.github.io/open-mes-demo-static/ is a read-only copy that runs entirely in your browser, with no server and no database (see [Docs/STATIC-DEMO.md](Docs/STATIC-DEMO.md)).

This repository is the **static demo**: the application code plus the builder that turns it into a static site. To run the real, editable app, use the companion repository [open-mes-demo-server](https://github.com/hadefuwa/open-mes-demo-server).

## Features

- **Work orders**: Entered → Allocated → Issued → In progress → QA → Complete, with a board, a technician job sheet, a printable work order and QA sign-off.
- **Traceability**: serial numbers, a full event history per unit, test reports and defects, all cross-linked.
- **Catalogue**: finished products, assemblies and components in one table, with indented BOM explosions, where-used, build time and cost roll-up (BOM cost + build time x labour rate).
- **Machines and routings**: availability, status control, and which products depend on which machine.
- **Planning**: a calendar timeline of what is built when and shipped when.
- **Quality**: test reports with step-by-step results, a defects log with wasted cost, first-pass yield.
- **Data browser**: every table in the database with its relationships and a CSV export.
- **Importers**: bills of materials (explosion sheets and flat design BOMs), a stock master, a price list and test-report workbooks.

## Quick start

Requires Python 3.12+. From the repository root (Windows PowerShell shown; use `source .venv/bin/activate` on macOS/Linux):

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
cd app
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py seed          # loads the generic dummy data pack
..\.venv\Scripts\python manage.py createsuperuser   # optional, for /admin/
..\.venv\Scripts\python manage.py runserver
```

Open http://127.0.0.1:8000/. Run `manage.py seed` again at any time to reset the demo.

Tests: `python manage.py test mes`

## Data packs

The software is generic. Everything specific to a business lives in a **data pack**: a single Python module in [app/mes/datapacks/](app/mes/datapacks) holding the catalogue, machines, routings, example orders and, optionally, a loader for real files. `manage.py seed --pack NAME` (or the `MES_DATA_PACK` setting) chooses one. The bundled `generic` pack is a small invented dataset; copy it to describe your own business. See [Docs/DATA-PACKS.md](Docs/DATA-PACKS.md).

## Status

An early, working demo (Django + SQLite, no login yet). The longer-term plan, including ERP adapters, is in [Docs/Plans/PLAN.md](Docs/Plans/PLAN.md). Machine connectivity (PLC/SCADA) is deliberately out of scope; events carry a `source` field so a machine layer can plug in later.

## Layout

```
app/
  config/            Django settings and URLs
  mes/               the application (models, views, importers, costing, tables)
    datapacks/       datasets: generic (dummy data) and any packs you add
    demo/            shared demo-data generators used by the seed command
scripts/             build_static_site.py builds the GitHub Pages demo
Docs/                plans, the data-pack guide and the static-demo notes
```
