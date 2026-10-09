# Data packs

A data pack is a Python module in `app/mes/datapacks/` that describes one dataset. The seed command loads it; nothing else in the code base knows which pack is in use.

```
manage.py seed                 # the pack named by the MES_DATA_PACK setting (default: generic)
manage.py seed --pack mypack   # a specific pack
```

`manage.py seed` **resets the database** first, so never run it against data you want to keep. It refuses to run on PostgreSQL, or with `DEBUG` off, unless you add `--force`.

## What a pack contains

Required catalogue data (see [generic.py](../app/mes/datapacks/generic.py) for a complete example):

| Attribute | Meaning |
|---|---|
| `TECHNICIANS`, `STATIONS` | names of production technicians and work areas |
| `FINISHED`, `ASSEMBLIES` | `[(code, name)]` |
| `COMPONENTS` | `[(code, name, category, unit cost)]` |
| `BOM` | `{parent code: [(child code, quantity)]}` |
| `MACHINES` | `[(name, kind, status, location, notes)]`; status is `available`, `in_use`, `maintenance` or `down` |
| `ROUTINGS` | `{product code: [(step name, machine name or None, minutes)]}` |
| `RRP` | `{finished product code: price}` (optional) |

Optional demo activity (leave these out for a pack that should contain real data only): `LIVE_ORDERS`, `HISTORY_PRODUCTS`, `HISTORY_STATIONS`, `HISTORY_START_NUMBER`, `CUSTOMER_ORDERS`, and the inputs to the area hooks (`HOOKS`, `BEST_SELLERS`, `CUSTOMERS`, `PLANNING_ORDERS`, `STOCK_BUILDS`, `MACHINE_NOTES`). The hooks are `catalogue` (sales history), `planning` (open orders and the timeline), `machines`, `defects` and `testreports`.

Optional real-data hooks:

- `load_real_data(command)`: import your own files. It runs after the example activity and before costs are worked out.
- `CALIBRATE_TO_RRP = True`: after a price list import, make each modelled product's BOM cost about a third of its RRP, topping up with a clearly labelled "other materials" line. This is a demo convenience; leave it off for real costs.
- `ESTIMATE_MISSING = False`: do not invent costs or routings for items that have none (the default invents plausible ones so demo pages are never empty).

`mes.datapacks.check_pack(pack)` validates a pack (unknown codes, machines, stations and technicians, duplicate codes, bad statuses). The seed command runs it first and stops with a readable list of problems.

## Importers

`mes/bom_import.py`, `mes/pricing.py` and `mes/importers.py` read Excel workbooks. A pack's `load_real_data` calls them with file paths (by default from a `data/` folder next to `app/`, configurable with `MES_DATA_DIR`).

- **BOM explosion sheet**: `Bom Level | Parent | Bom Structure | Description | Seq. | Quantity | Unit`. Replaces each parent's BOM on every import.
- **Flat design BOM** (one product per sheet, product code taken from the file name): a part-name column, description, quantity, cost per pack, pack size, supplier and process columns. In-house 3D-print and CNC parts get routing steps.
- **Stock master**: `Product Code | Description | Supplier | Part No. | ... | Re-Order Level | ... | Last Cost Price (Std) | ... | Free Stock`.
- **Price list**: a `Prices` sheet of `Code | Description | RRP`, with section headings becoming the product range.
- **Test reports**: a `Summary` sheet plus one sheet per report.

After importing, `mes/classify.py` decides whether each item is a finished product, an assembly or a component from the BOM structure.

Real source workbooks contain prices, supplier terms and sometimes customer data. They are git-ignored by default (`data/`, `*.xlsx`, `*.xlsm`); keep them out of any public repository.
