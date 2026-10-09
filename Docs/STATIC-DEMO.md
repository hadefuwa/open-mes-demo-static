# Static demo (GitHub Pages)

A read-only copy of the app that runs in any browser with **no server and no database**. It is built from the generic dummy data, so it is safe to publish.

Live: https://hadefuwa.github.io/open-mes-demo-static/

## What works

Everything you can *look at*: the dashboard and its charts, the work order board, every work order, products, assemblies, components, bills of materials and where-used, machines, the planning timeline, customer orders, test reports, defects, traceability by serial number and the data browser. Tables can be searched and sorted, and exported to CSV, in the browser. Selecting a workstation, a technician or a serial number jumps to the matching page.

## What does not

- Buttons that change data (allocate, start, finish, approve, raise a works order, change machine status, record a defect) show a "read-only demo" notice. Use the real app for those.
- The timeline shows the default view plus up to 8 weeks either side; its filters are hidden.
- It is a snapshot of one seeded dataset, not live data.

## How it is built

`manage.py build_static_site` crawls the app in-process with `MES_STATIC_EXPORT` switched on, saves every page as HTML with relative links (so it works from any folder or URL path, including a GitHub Pages project site), and writes a manifest of the pre-rendered pages. In that mode the table template renders every row on one page and drops the server-side search, sort and paging controls; `app/mes/static_site/demo.js` provides them in the browser. Forms that would normally hit the server look their target up in the manifest instead (`/board/?station=3` becomes `board/index--station-3.html`).

```
python scripts/build_static_site.py            # builds ./site from the generic pack, using a throwaway database
```

Open `site/index.html` directly, or serve the folder with any static host.

## Publishing

The live site is the contents of `site/` on the `gh-pages` branch (repository Settings > Pages > Deploy from a branch > `gh-pages` / root). To update it, rebuild and replace the branch contents; a zip of the same folder is attached to each GitHub release.

## Adding pages

New pages join the site automatically if they are reachable by links. If a page adds a GET form that changes what is shown, either make sure each result is linked from somewhere (it will then be crawled) or add seed URLs in `Command.crawl`. `tests_static_site.py` fails if any link in the generated site points at a missing file.
