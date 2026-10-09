from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import quote

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .permissions import require_role

from . import bom, costing
from .models import Defect, Event, ProductionTechnician, Unit, WorkOrder
from .tables import Column, build_table

CENT = Decimal("0.01")
WHOLE_UNIT = "whole"


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def component_choices(order):
    """Parts that can be reported defective on an order: the flattened BOM components of its product."""
    return [f.product for f in bom.flat_components(order.product)]


def record_scrap(unit, order, description):
    """Create the whole-unit defect for a scrapped unit, once per unit and description."""
    description = (description or "Scrapped")[:300]
    if Defect.objects.filter(unit=unit, description=description, component__isnull=True).exists():
        return None
    return Defect.objects.create(
        product=order.product, work_order=order, unit=unit, quantity=1,
        unit_cost=money(costing.total_cost(order.product)), description=description,
        reported_by=order.technician)


def month_start(now=None):
    now = timezone.localtime(now or timezone.now())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _rank(defects, key):
    totals = {}
    for d in defects:
        obj = key(d)
        if obj is None:
            continue
        entry = totals.setdefault(obj.pk, {"obj": obj, "label": obj.code, "cost": Decimal("0"), "qty": 0})
        entry["cost"] += d.cost
        entry["qty"] += d.quantity
    return sorted(totals.values(), key=lambda e: -e["cost"])


def _rank_causes(defects):
    totals = defaultdict(lambda: Decimal("0"))
    for d in defects:
        totals[d.description] += d.cost
    return [{"label": k, "cost": v} for k, v in sorted(totals.items(), key=lambda kv: -kv[1])]


def _with_pct(rows):
    top = rows[0]["cost"] if rows else 1
    for r in rows:
        r["pct"] = float(100 * r["cost"] / top) if top else 0
    return rows


def defects(request):
    qs = list(Defect.objects.select_related("product", "component", "work_order", "unit", "reported_by"))
    columns = [
        Column("when", "When", "occurred_at", fmt="datetime"),
        Column("part", "Defective part", lambda d: d.component.code if d.component else "Whole unit",
               url=lambda d: d.component.get_absolute_url() if d.component else None, mono=True),
        Column("part_desc", "Part description",
               lambda d: d.component.name if d.component else f"Complete {d.product.name}"),
        Column("product", "Product being built", "product.code",
               url=lambda d: d.product.get_absolute_url(), mono=True),
        Column("order", "Work order", "work_order.number",
               url=lambda d: f"/operator/{d.work_order_id}/" if d.work_order_id else None),
        Column("serial", "Serial", "unit.serial",
               url=lambda d: f"/traceability/?serial={quote(d.unit.serial)}" if d.unit else None),
        Column("qty", "Qty", "quantity", numeric=True),
        Column("unit_cost", "Unit cost", "unit_cost", numeric=True, fmt="money"),
        Column("cost", "Total cost", lambda d: d.cost, numeric=True, fmt="money"),
        Column("description", "Description", "description"),
        Column("by", "Reported by", "reported_by.name"),
        Column("created", "Created", "created_at", fmt="datetime"),
        Column("updated", "Updated", "updated_at", fmt="datetime"),
    ]
    table, csv_response = build_table(request, columns, qs, filename="defects",
                                      default_sort="when", default_desc=True)
    if csv_response:
        return csv_response

    start = month_start()
    this_month = [d for d in qs if d.occurred_at >= start]
    parts = _with_pct(_rank([d for d in qs if d.component_id], lambda d: d.component))
    products = _rank(qs, lambda d: d.product)
    causes = _with_pct(_rank_causes(qs))
    return render(request, "mes/defects/defects.html", {
        "table": table,
        "stats": {
            "month_count": len(this_month),
            "month_cost": sum((d.cost for d in this_month), Decimal("0")),
            "total_cost": sum((d.cost for d in qs), Decimal("0")),
            "total_count": len(qs),
            "top_part": parts[0] if parts else None,
            "top_product": products[0] if products else None,
        },
        "parts": parts[:6],
        "causes": causes[:6],
    })


@require_POST
@require_role("work")
def defect_add(request, order_pk):
    order = get_object_or_404(WorkOrder.objects.select_related("product", "technician"), pk=order_pk)
    post = request.POST
    description = post.get("description", "").strip()[:300]
    part = post.get("component", "")
    serial = post.get("serial", "").strip()

    def back(error=None, notice=None):
        param = f"?error={quote(error)}" if error else f"?notice={quote(notice)}" if notice else ""
        return redirect(f"/operator/{order.pk}/{param}")

    if order.status not in (WorkOrder.IN_PROGRESS, WorkOrder.QA):
        return back("Defects can only be recorded while the order is in progress or in QA")
    try:
        quantity = int(post.get("quantity", ""))
    except ValueError:
        quantity = 0
    if quantity < 1 or quantity > 10000:
        return back("Quantity must be a whole number of at least 1")
    if not description:
        return back("Describe the defect")

    unit = None
    if serial:
        unit = Unit.objects.filter(work_order=order, serial=serial).first()
        if not unit:
            return back(f"Serial {serial} is not on this order")

    component = None
    if part == WHOLE_UNIT:
        unit_cost = costing.total_cost(order.product)
    elif part:
        component = next((p for p in component_choices(order) if str(p.pk) == part), None)
        if not component:
            return back("That part is not in the bill of materials for this product")
        unit_cost = component.unit_cost
    else:
        return back("Choose the defective part")

    reporter = None
    if post.get("reported_by"):
        reporter = ProductionTechnician.objects.filter(pk=post["reported_by"]).first() \
            if post["reported_by"].isdigit() else None
        if not reporter:
            return back("Unknown technician")

    defect = Defect.objects.create(
        product=order.product, component=component, work_order=order, unit=unit, quantity=quantity,
        unit_cost=money(unit_cost), description=description, reported_by=reporter or order.technician)
    what = component.code if component else "whole unit"
    Event.objects.create(work_order=order, unit=unit, action="defect recorded",
                         detail=f"{quantity} x {what}: {description}"[:300])
    return back(notice=f"Defect recorded: {quantity} x {what}, cost £{defect.cost:,.2f}")
