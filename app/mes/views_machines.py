from django.db.models import Count
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .permissions import require_role

from .models import BomLine, Machine, Product, RoutingStep, WorkOrder
from .tables import Column, build_table

STATUS_PILL = {Machine.AVAILABLE: "ok", Machine.IN_USE: "info", Machine.MAINTENANCE: "warn", Machine.DOWN: "bad"}
PRODUCT_KIND_PILL = {Product.FINISHED: "info", Product.ASSEMBLY: "ok", Product.COMPONENT: ""}


def affected_products(machine):
    """Products with a routing step on the machine, plus everything that contains them in its BOM."""
    direct = set(RoutingStep.objects.filter(machine=machine).values_list("product_id", flat=True))
    seen, frontier = set(direct), set(direct)
    while frontier:
        parents = set(BomLine.objects.filter(child_id__in=frontier).values_list("parent_id", flat=True))
        frontier = parents - seen
        seen |= parents
    return direct, seen


def machine_impact(machine):
    direct_ids, all_ids = affected_products(machine)
    finished = list(Product.objects.filter(pk__in=all_ids, kind=Product.FINISHED).order_by("code"))
    orders = list(WorkOrder.objects.filter(product_id__in=all_ids).exclude(status=WorkOrder.COMPLETE)
                  .select_related("product").order_by("due_date", "number"))
    return direct_ids, finished, orders


def machines(request):
    rows = list(Machine.objects.annotate(product_count=Count("routing_steps__product", distinct=True)))
    counts = {s: sum(1 for m in rows if m.status == s) for s, _ in Machine.STATUS_CHOICES}
    columns = [
        Column("name", "Machine", "name", url=lambda m: reverse("machine_detail", args=[m.pk])),
        Column("kind", "Kind", "kind"),
        Column("status", "Status", lambda m: m.get_status_display(), pill=lambda m: STATUS_PILL[m.status]),
        Column("location", "Location", "location"),
        Column("products", "Product codes", "product_count", numeric=True),
        Column("notes", "Notes", "notes"),
        Column("created", "Created", "created_at", fmt="datetime"),
        Column("updated", "Updated", "updated_at", fmt="datetime"),
    ]
    table, csv_response = build_table(request, columns, rows, filename="machines", default_sort="name")
    if csv_response:
        return csv_response
    return render(request, "mes/machines/machines.html", {"table": table, "total": len(rows), "counts": counts})


def machine_detail(request, pk):
    machine = get_object_or_404(Machine, pk=pk)
    direct_ids, finished, orders = machine_impact(machine)
    steps = {s.product_id: s for s in machine.routing_steps.select_related("product").order_by("sequence")}
    product_columns = [
        Column("code", "Code", "product.code", url=lambda s: s.product.get_absolute_url(), mono=True),
        Column("name", "Name", "product.name"),
        Column("kind", "Kind", lambda s: s.product.get_kind_display(), pill=lambda s: PRODUCT_KIND_PILL[s.product.kind]),
        Column("step", "Routing step", "name"),
        Column("minutes", "Minutes", "minutes", numeric=True, fmt="minutes"),
        Column("updated", "Updated", "updated_at", fmt="datetime"),
    ]
    table, csv_response = build_table(request, product_columns, list(steps.values()),
                                      filename=f"machine-{machine.pk}-products", default_sort="code")
    if csv_response:
        return csv_response

    finished_ids = {p.pk for p in finished}
    finished_rows = [{"product": p, "direct": p.pk in direct_ids,
                      "open": sum(1 for o in orders if o.product_id == p.pk)} for p in finished]
    blocked = not machine.is_available
    ctx = {
        "machine": machine, "table": table, "pill": STATUS_PILL[machine.status], "statuses": Machine.STATUS_CHOICES,
        "finished_rows": finished_rows, "orders": orders, "blocked": blocked,
        "impact_products": len(finished_ids), "impact_orders": len(orders),
    }
    return render(request, "mes/machines/machine_detail.html", ctx)


@require_POST
@require_role("machine")
def machine_status(request, pk):
    machine = get_object_or_404(Machine, pk=pk)
    status = request.POST.get("status", "")
    if status not in dict(Machine.STATUS_CHOICES):
        return HttpResponseBadRequest("Unknown status")
    machine.status = status
    machine.save()
    return redirect("machine_detail", pk=pk)
