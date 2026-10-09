"""Import real bills of materials and stock data from workbooks.

Each sheet is recognised by its header row, so one workbook can hold several layouts and unknown
sheets (customer accounts, notes) are skipped untouched:

  * BOM explosion:  Bom Level | Parent | Bom Structure | Description | Seq. | Quantity | Unit
    Level 0 is the top product. Every line becomes a BomLine; the BOM of each parent seen in the
    file is replaced, so re-importing never stacks lines.
  * Stock master:   Product Code | Description | Supplier A/C | Part No. | Quantity Allocated |
    Quantity On Order | Re-Order Level | Re-Order Quantity | Last Cost Price (Std) | ... | Free Stock
    Sets description, cost, supplier and stock levels. Codes not already known become components.

  * BOM register:  Bom Reference | Description | Type | Category | Revision | Unit Cost | Category Name
    The ERP's item type and standard cost for every manufactured item (no structure).
  * Stock records: Stock Code | Description | Category | Item Type | Quantity in Stock
    On-hand quantities and whether the item is stocked.
  * Design BOM:    a flat one-product sheet (see import_design_bom).

Kinds (finished / assembly / component) are decided afterwards by mes.classify.
"""
import hashlib
import math
import re
from collections import defaultdict
from decimal import Decimal

from django.db import transaction

from .models import BomLine, Product, RoutingStep


def category_of(code):
    """Code prefix: FG1001 -> FG, 3DP01300 -> 3DP, ELE1001 -> ELE."""
    match = re.match(r"\d*[A-Za-z]+", code)
    return match.group().upper() if match else ""


def _text(value):
    return "" if value is None else str(value).strip()


def _number(value, default=None):
    try:
        return Decimal(str(value).strip()) if value not in (None, "") else default
    except Exception:
        return default


def _header(row):
    return {_text(v).lower(): i for i, v in enumerate(row) if _text(v)}


def _load_sheets(path):
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in workbook}
    finally:
        workbook.close()  # read-only workbooks keep the file locked on Windows until closed


def _find_header(rows, required, limit=6):
    for i, row in enumerate(rows[:limit]):
        idx = _header(row)
        if all(name in idx for name in required):
            return i, idx
    return None, None


@transaction.atomic
def import_explosion(rows):
    """One BOM explosion sheet. Returns (products touched, lines created)."""
    start, idx = _find_header(rows, ("bom level", "parent", "bom structure"))
    if start is None:
        return 0, 0
    get = lambda r, name: r[idx[name]] if name in idx and idx[name] < len(r) else None

    products, lines, parents = {}, defaultdict(Decimal), []
    sequence = {}
    for row in rows[start + 1:]:
        child = _text(get(row, "bom structure"))
        if not child:
            continue
        description = _text(get(row, "description"))
        if child not in products:
            product = Product.objects.filter(code=child).first()
            if product is None:
                product = Product.objects.create(code=child, name=description or child, kind=Product.COMPONENT)
            elif description:
                product.name = description
                product.save(update_fields=["name"])
            products[child] = product
        parent = _text(get(row, "parent"))
        if parent:
            key = (parent, child)
            lines[key] += _number(get(row, "quantity"), Decimal(1)) or Decimal(1)
            sequence.setdefault(key, int(_number(get(row, "seq."), len(sequence) + 1) or 0))
            if parent not in parents:
                parents.append(parent)

    created = 0
    for parent in parents:
        BomLine.objects.filter(parent__code=parent).delete()
    for (parent, child), qty in lines.items():
        if parent not in products:
            continue
        BomLine.objects.create(parent=products[parent], child=products[child], quantity=qty.quantize(Decimal("0.01")),
                               sequence=sequence[(parent, child)])
        created += 1
    return len(products), created


@transaction.atomic
def import_stock_master(rows):
    """One stock-master sheet. Returns (created, updated)."""
    start, idx = _find_header(rows, ("product code", "description", "last cost price (std)"))
    if start is None:
        return 0, 0
    get = lambda r, name: r[idx[name]] if name in idx and idx[name] < len(r) else None

    existing = {p.code: p for p in Product.objects.all()}
    new, changed = [], []
    for row in rows[start + 1:]:
        code = _text(get(row, "product code"))
        if not code:
            continue
        description = _text(get(row, "description"))
        cost = _number(get(row, "last cost price (std)"))
        cost = cost.quantize(Decimal("0.0001")) if cost and cost > 0 else None
        stock = _number(get(row, "free stock"))
        reorder = _number(get(row, "re-order level"))
        fields = {
            "supplier_code": _text(get(row, "supplier a/c")),
            "supplier_part_no": _text(get(row, "part no.")),
            "free_stock": int(stock) if stock is not None else None,
            "reorder_level": int(reorder) if reorder is not None and reorder >= 0 else None,
        }
        product = existing.get(code)
        if product is None:
            product = Product(code=code, name=description or code, kind=Product.COMPONENT,
                              category=category_of(code), unit_cost=cost, **fields)
            existing[code] = product
            new.append(product)
        else:
            for name, value in fields.items():
                setattr(product, name, value)
            if cost is not None and product.kind == Product.COMPONENT:
                product.unit_cost = cost
            if description and product.name in ("", product.code):
                product.name = description
            changed.append(product)
    Product.objects.bulk_create(new, batch_size=500)
    Product.objects.bulk_update(changed, ["supplier_code", "supplier_part_no", "free_stock", "reorder_level",
                                          "unit_cost", "name"], batch_size=500)
    return len(new), len(changed)


def kind_from_erp_type(erp_type):
    """Map an ERP item type ("Finished Goods", "Sub-Assembly", "Component") to a Product kind, or None."""
    t = _text(erp_type).lower()
    if "finished" in t:
        return Product.FINISHED
    if "assembl" in t:
        return Product.ASSEMBLY
    if "component" in t:
        return Product.COMPONENT
    return None


@transaction.atomic
def import_bom_register(rows):
    """A register of BOM headers: Bom Reference | Description | Type | Category | Revision | Unit Cost |
    Category Name. It carries the ERP's own item type and standard cost for every manufactured item but not the
    structure (use an explosion sheet for that). Returns (created, updated).

    The ERP standard cost is kept as `standard_cost`. Items whose structure we have not imported also use it
    as their unit cost, so costs stay real; items with an imported BOM keep the cost rolled up from it."""
    start, idx = _find_header(rows, ("bom reference", "description", "type", "unit cost"))
    if start is None:
        return 0, 0
    get = lambda r, name: r[idx[name]] if name in idx and idx[name] < len(r) else None

    existing = {p.code: p for p in Product.objects.all()}
    structured = set(BomLine.objects.values_list("parent__code", flat=True))
    new, changed = [], []
    for row in rows[start + 1:]:
        code = _text(get(row, "bom reference"))
        if not code:
            continue
        description = _text(get(row, "description"))
        erp_type = _text(get(row, "type"))
        cost = _number(get(row, "unit cost"))
        cost = cost.quantize(Decimal("0.0001")) if cost and cost > 0 else None
        product = existing.get(code)
        created = product is None
        if created:
            product = Product(code=code, name=description or code, category=category_of(code),
                              kind=kind_from_erp_type(erp_type) or Product.COMPONENT)
            existing[code] = product
        elif description:
            product.name = description
        product.erp_type, product.revision = erp_type, _text(get(row, "revision"))[:20]
        product.standard_cost = cost
        category_name = _text(get(row, "category name"))
        if category_name and not product.range_name:
            product.range_name = category_name[:60]
        if cost is not None and code not in structured:
            product.unit_cost = cost
        (new if created else changed).append(product)
    Product.objects.bulk_create(new, batch_size=500)
    Product.objects.bulk_update(changed, ["name", "erp_type", "revision", "standard_cost", "range_name", "unit_cost"],
                                batch_size=500)
    return len(new), len(changed)


@transaction.atomic
def import_stock_records(rows):
    """Stock levels: Stock Code | Description | Category | Item Type | Quantity in Stock. Sets the on-hand
    quantity and whether the item is stocked. Unknown codes become components. Returns (created, updated)."""
    start, idx = _find_header(rows, ("stock code", "item type", "quantity in stock"))
    if start is None:
        return 0, 0
    get = lambda r, name: r[idx[name]] if name in idx and idx[name] < len(r) else None

    existing = {p.code: p for p in Product.objects.all()}
    new, changed = [], []
    for row in rows[start + 1:]:
        code = _text(get(row, "stock code"))
        if not code:
            continue
        quantity = _number(get(row, "quantity in stock"))
        stocked = not _text(get(row, "item type")).lower().startswith("non")
        description = _text(get(row, "description"))
        product = existing.get(code)
        if product is None:
            product = Product(code=code, name=description or code, kind=Product.COMPONENT,
                              category=category_of(code), stock_quantity=quantity, is_stocked=stocked)
            existing[code] = product
            new.append(product)
        else:
            product.stock_quantity, product.is_stocked = quantity, stocked
            if description and product.name in ("", product.code):
                product.name = description
            changed.append(product)
    Product.objects.bulk_create(new, batch_size=500)
    Product.objects.bulk_update(changed, ["stock_quantity", "is_stocked", "name"], batch_size=500)
    return len(new), len(changed)


def _duration_minutes(value):
    """'10m57s' -> 10.95, '1h5m' -> 65. Returns None when there is no usable time."""
    text = _text(value).lower()
    parts = {unit: int(n) for n, unit in re.findall(r"(\d+)\s*([hms])", text)}
    if not parts:
        return None
    return Decimal(parts.get("h", 0) * 60 + parts.get("m", 0)) + Decimal(parts.get("s", 0)) / 60


def _machine(fragment):
    from .models import Machine
    return Machine.objects.filter(name__icontains=fragment).first()


@transaction.atomic
def import_design_bom(rows, top_code, top_name=None):
    """A flat design BOM for one product: one row per part with a code, description, quantity,
    cost per pack, pack size, supplier and process details. Returns the number of BOM lines.

    Header names are matched loosely: the part-code column is the one whose header contains
    "part name"; others are DESCRIPTION, QTY., COST, PACK SIZE, SUPPLIER, ORDER PRODUCT CODE,
    TYPE and "Time to print". Cost is per pack, so unit cost = cost / pack size. Parts of type
    3D print or CNC are made in-house and get a routing step on the matching machine; everything
    else is treated as bought in.
    """
    start, idx = _find_header(rows, ("description", "qty."))
    if start is None:
        return 0
    code_col = next((i for name, i in idx.items() if "part name" in name), None)
    if code_col is None:
        return 0
    col = lambda r, name: r[idx[name]] if name in idx and idx[name] < len(r) else None

    parts, quantities, group = {}, defaultdict(Decimal), ""
    for row in rows[start + 1:]:
        group = _text(col(row, "type")) or group
        code = _text(row[code_col] if code_col < len(row) else None)
        if not code:
            continue
        quantities[code] += _number(col(row, "qty."), Decimal(1)) or Decimal(1)
        parts.setdefault(code, (row, group))

    top = Product.objects.filter(code=top_code).first()
    if top is None:
        top = Product.objects.create(code=top_code, name=top_name or top_code, kind=Product.FINISHED)
    elif top_name:
        top.name = top_name
        top.save(update_fields=["name"])
    BomLine.objects.filter(parent=top).delete()

    for sequence, (code, (row, kind_group)) in enumerate(parts.items(), start=1):
        product = Product.objects.filter(code=code).first()
        if product is None:
            product = Product(code=code, kind=Product.COMPONENT, category=category_of(code))
        product.name = _text(col(row, "description")) or product.name or code
        cost, pack = _number(col(row, "cost")), _number(col(row, "pack size"), Decimal(1)) or Decimal(1)
        if cost and cost > 0:
            product.unit_cost = (cost / pack).quantize(Decimal("0.0001"))
        supplier = _text(col(row, "supplier"))
        if supplier:
            product.supplier_code = supplier[:30]
        if _text(col(row, "order product code")):
            product.supplier_part_no = _text(col(row, "order product code"))[:60]
        product.save()
        BomLine.objects.create(parent=top, child=product, quantity=quantities[code].quantize(Decimal("0.01")),
                               sequence=sequence * 10)

        group_name = kind_group.lower()
        if "3d" in group_name:
            machine, minutes, step = _machine("3d"), _duration_minutes(col(row, "time to print (per 1)")), "3D print"
        elif "cnc" in group_name:
            machine, minutes, step = _machine("cnc mill"), Decimal(10), "CNC machine"  # no time given: assumed
        else:
            continue
        RoutingStep.objects.filter(product=product).delete()
        RoutingStep.objects.create(product=product, sequence=10, name=step, machine=machine,
                                   minutes=(minutes or Decimal(5)).quantize(Decimal("0.1")))
    return len(parts)


def code_from_filename(path):
    """'AB1234 BOM.xlsx' -> 'AB1234' (the product this design BOM describes)."""
    from pathlib import Path
    match = re.match(r"[A-Za-z]{1,4}\d{3,6}[A-Za-z0-9-]*", Path(path).stem.strip())
    return match.group() if match else None


def import_workbook(path, names=None):
    """Import every recognised sheet in a workbook. `names` optionally maps a product code to its name.
    Returns a summary dict."""
    summary = {"explosions": 0, "bom_lines": 0, "stock_created": 0, "stock_updated": 0,
               "register_created": 0, "register_updated": 0, "records_created": 0, "records_updated": 0}
    top_code = code_from_filename(path)
    for rows in _load_sheets(path).values():
        created, updated = import_bom_register(rows)
        summary["register_created"] += created
        summary["register_updated"] += updated
        created, updated = import_stock_records(rows)
        summary["records_created"] += created
        summary["records_updated"] += updated
        touched, lines = import_explosion(rows)
        if lines:
            summary["explosions"] += 1
            summary["bom_lines"] += lines
        if top_code:
            designed = import_design_bom(rows, top_code, (names or {}).get(top_code))
            if designed:
                summary["explosions"] += 1
                summary["bom_lines"] += designed
        created, updated = import_stock_master(rows)
        summary["stock_created"] += created
        summary["stock_updated"] += updated
    return summary


# Plausible cost range (low, high) in pounds per category, for parts the stock master does not cost.
_COST_RANGES = {
    "COM": (0.4, 18), "FIX": (0.02, 0.35), "REE": (0.01, 0.4), "RES": (0.01, 0.3), "MET": (0.8, 14),
    "LAS": (0.15, 3), "PCB": (0.8, 7), "ICS": (0.4, 6), "CON": (0.08, 1.2), "3DP": (0.3, 2), "PLAS": (0.2, 3),
    "WIR": (0.2, 3),
}


def estimated_cost(code, category):
    """Deterministic made-up cost, log-scaled within the category's range, so reruns agree."""
    low, high = _COST_RANGES.get(category, (0.5, 15))
    fraction = int(hashlib.sha1(code.encode()).hexdigest()[:8], 16) % 10000 / 10000
    return Decimal(str(round(low * math.exp(math.log(high / low) * fraction), 4)))


def fill_missing_costs():
    """Give every costless component a plausible invented cost. Returns how many were filled."""
    todo = list(Product.objects.filter(kind=Product.COMPONENT, unit_cost__isnull=True))
    for product in todo:
        product.unit_cost = estimated_cost(product.code, product.category or category_of(product.code))
    Product.objects.bulk_update(todo, ["unit_cost"], batch_size=500)
    return len(todo)


def ensure_routings():
    """Assemblies and products with a BOM but no routing get one assemble step, sized by BOM length."""
    made = 0
    for product in Product.objects.filter(bom_lines__isnull=False, routing_steps__isnull=True).distinct():
        minutes = max(5, round(product.bom_lines.count() * 0.5))
        RoutingStep.objects.create(product=product, sequence=10, name="Assemble", minutes=Decimal(minutes))
        made += 1
    return made
