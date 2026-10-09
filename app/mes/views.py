from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .permissions import require_role

from . import views_defects
from .models import (CustomerOrder, CustomerOrderLine, Defect, Event, ProductionTechnician, TestReport, Unit,
                     WorkOrder,
                     Workstation)


def _log(order, action, detail="", unit=None):
    Event.objects.create(work_order=order, unit=unit, action=action, detail=detail)


def _back(pk, error=None):
    return redirect(f"/operator/{pk}/?error={error}" if error else f"/operator/{pk}/")


def board(request):
    orders = WorkOrder.objects.select_related("product", "workstation", "technician")
    station = request.GET.get("station")
    if station:
        orders = orders.filter(workstation_id=station)
    orders = list(orders.annotate(unit_count=Count("units")))
    columns = []
    for value, label in WorkOrder.STATUS_CHOICES:
        in_column = [o for o in orders if o.status == value]
        if value == WorkOrder.COMPLETE:  # most recent first, capped so the board stays readable
            in_column.sort(key=lambda o: o.due_date or date.min, reverse=True)
        shown = in_column[:6] if value == WorkOrder.COMPLETE else in_column
        columns.append((value, label, shown, len(in_column) - len(shown)))
    return render(request, "mes/board.html", {
        "columns": columns,
        "stations": Workstation.objects.all(),
        "selected": station,
    })


def my_jobs(request):
    """An technician's job sheet: their issued and in-progress orders."""
    technicians = ProductionTechnician.objects.all()
    selected = request.GET.get("technician")
    orders = []
    if selected:
        orders = WorkOrder.objects.select_related("product", "workstation").filter(
            technician_id=selected,
            status__in=[WorkOrder.ISSUED, WorkOrder.IN_PROGRESS, WorkOrder.QA],
        )
    return render(request, "mes/my_jobs.html", {
        "technicians": technicians, "selected": selected, "orders": orders,
        "total_minutes": sum(o.est_minutes or 0 for o in orders),
    })


def operator(request, pk):
    order = get_object_or_404(
        WorkOrder.objects.select_related("product", "workstation", "technician"), pk=pk)
    keys = [value for value, _ in WorkOrder.STATUS_CHOICES]
    current = keys.index(order.status)
    steps = [
        (label, "done" if i < current or order.status == WorkOrder.COMPLETE
         else "current" if i == current else "todo")
        for i, (_, label) in enumerate(WorkOrder.STATUS_CHOICES)
    ]
    return render(request, "mes/operator.html", {
        "order": order,
        "steps": steps,
        "units": order.units.prefetch_related("test_reports"),
        "technicians": ProductionTechnician.objects.all(),
        "error": request.GET.get("error"),
    })


def _advance(request, pk, from_status, to_status, action):
    order = get_object_or_404(WorkOrder, pk=pk)
    if order.status == from_status:
        order.status = to_status
        order.save()
        _log(order, action)
    return _back(pk)


@require_POST
@require_role("stock")
def allocate(request, pk):
    return _advance(request, pk, WorkOrder.ENTERED, WorkOrder.ALLOCATED, "stock allocated")


@require_POST
@require_role("stock")
def issue(request, pk):
    return _advance(request, pk, WorkOrder.ALLOCATED, WorkOrder.ISSUED, "stock issued")


@require_POST
@require_role("assign")
def assign(request, pk):
    order = get_object_or_404(WorkOrder, pk=pk)
    technician = ProductionTechnician.objects.filter(pk=request.POST.get("technician")).first()
    order.technician = technician
    order.save()
    _log(order, "assigned", technician.name if technician else "unassigned")
    return _back(pk)


def print_sheet(request, pk):
    """Printable work order; viewing it marks the order as printed."""
    order = get_object_or_404(
        WorkOrder.objects.select_related("product", "workstation", "technician"), pk=pk)
    if not order.printed:
        order.printed = True
        order.save()
        _log(order, "printed")
    return render(request, "mes/print.html", {"order": order})


@require_POST
@require_role("work")
def start(request, pk):
    return _advance(request, pk, WorkOrder.ISSUED, WorkOrder.IN_PROGRESS, "started")


@require_POST
@require_role("work")
def add_unit(request, pk):
    order = get_object_or_404(WorkOrder, pk=pk)
    serial = request.POST.get("serial", "").strip()
    result = request.POST.get("result", Unit.PENDING)
    reason = request.POST.get("reason", "").strip()
    if order.status != WorkOrder.IN_PROGRESS:
        return _back(pk, "Start the job first")
    if not serial:
        return _back(pk, "Serial number required")
    if Unit.objects.filter(serial=serial).exists():
        return _back(pk, f"Serial {serial} already exists")
    if result in (Unit.REWORK, Unit.SCRAP) and not reason:
        return _back(pk, "Give a reason for rework or scrap")
    unit = Unit.objects.create(
        work_order=order, serial=serial, result=result, reason=reason,
        first_pass=result in (Unit.PASS, Unit.PENDING),
    )
    _log(order, "unit recorded", f"{result}" + (f": {reason}" if reason else ""), unit)
    if result == Unit.SCRAP:
        views_defects.record_scrap(unit, order, reason)
    return _back(pk)


@require_POST
@require_role("work")
def retest_unit(request, pk, unit_id):
    """Record a new result for a unit sent to rework (it is no longer first-pass)."""
    order = get_object_or_404(WorkOrder, pk=pk)
    unit = get_object_or_404(Unit, pk=unit_id, work_order=order)
    result = request.POST.get("result")
    if result in (Unit.PASS, Unit.REWORK, Unit.SCRAP):
        unit.result = result
        unit.first_pass = False
        unit.save()
        _log(order, "unit retested", result, unit)
        if result == Unit.SCRAP:
            views_defects.record_scrap(unit, order, unit.reason)
    return _back(pk)


@require_POST
@require_role("work")
def finish(request, pk):
    """ProductionTechnician finishes the build and test; the order moves to QA."""
    order = get_object_or_404(WorkOrder, pk=pk)
    if order.status != WorkOrder.IN_PROGRESS:
        return _back(pk)
    open_units = order.units.filter(result__in=[Unit.PENDING, Unit.REWORK]).count()
    if open_units:
        return _back(pk, f"{open_units} unit(s) still pending or in rework")
    order.status = WorkOrder.QA
    order.save()
    _log(order, "sent to QA")
    return _back(pk)


@require_POST
@require_role("qa")
def approve(request, pk):
    """Team leader signs off QA and completes the order."""
    order = get_object_or_404(WorkOrder, pk=pk)
    if order.status == WorkOrder.QA:
        order.status = WorkOrder.COMPLETE
        order.save()
        _log(order, "QA approved, completed")
        return redirect("board")
    return _back(pk)


@require_POST
@require_role("qa")
def reject(request, pk):
    """Team leader sends the order back to the technician."""
    order = get_object_or_404(WorkOrder, pk=pk)
    if order.status == WorkOrder.QA:
        order.status = WorkOrder.IN_PROGRESS
        order.save()
        _log(order, "QA rejected, returned to build")
    return _back(pk)


def customer_orders(request):
    orders = CustomerOrder.objects.prefetch_related("lines__product", "lines__work_order")
    return render(request, "mes/customer_orders.html", {"orders": orders})


def customer_order(request, pk):
    order = get_object_or_404(
        CustomerOrder.objects.prefetch_related("lines__product", "lines__work_order"), pk=pk)
    return render(request, "mes/customer_order.html", {"order": order})


@require_POST
@require_role("raise")
def raise_work_order(request, pk, line_id):
    """Create a work order (status Entered) to fulfil one customer order line."""
    line = get_object_or_404(CustomerOrderLine, pk=line_id, order_id=pk)
    if line.work_order_id is None:
        numbers = [int(n) for n in WorkOrder.objects.values_list("number", flat=True) if n.isdigit()]
        wo = WorkOrder.objects.create(
            number=str(max(numbers, default=3400) + 1),
            product=line.product, quantity=line.quantity,
        )
        line.work_order = wo
        line.save()
        _log(wo, "raised", f"from customer order {line.order.number}")
    return redirect("customer_order", pk=pk)


def traceability(request):
    query = request.GET.get("serial", "").strip()
    unit = Unit.objects.select_related("work_order__product").filter(serial__iexact=query).first() if query else None
    return render(request, "mes/traceability.html", {
        "query": query,
        "unit": unit,
        "history": unit.events.all() if unit else [],
    })


def dashboard(request):
    today = date.today()
    status_counts = {r["status"]: r["n"] for r in WorkOrder.objects.values("status").annotate(n=Count("id"))}
    status_data = [
        {"key": value, "label": label, "value": status_counts.get(value, 0)}
        for value, label in WorkOrder.STATUS_CHOICES
    ]

    open_orders = list(WorkOrder.objects.exclude(status=WorkOrder.COMPLETE)
                       .select_related("product", "technician"))
    overdue = [o for o in open_orders if o.is_overdue]
    due_soon = [o for o in open_orders if o.due_soon and not o.is_overdue]
    in_qa = [o for o in open_orders if o.status == WorkOrder.QA]

    totals = Unit.objects.aggregate(
        first_pass=Count("id", filter=Q(first_pass=True, result=Unit.PASS)),
        tested=Count("id", filter=~Q(result=Unit.PENDING)),
        scrapped=Count("id", filter=Q(result=Unit.SCRAP)),
    )
    fpy = round(100 * totals["first_pass"] / totals["tested"], 1) if totals["tested"] else None

    # Last 14 days of units and first-pass yield
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    per_day = {}
    for unit in Unit.objects.filter(created_at__date__gte=days[0]).exclude(result=Unit.PENDING):
        d = timezone.localtime(unit.created_at).date()
        row = per_day.setdefault(d, [0, 0])
        row[0] += 1
        row[1] += unit.first_pass and unit.result == Unit.PASS
    units_per_day = [{"label": d.strftime("%d %b"), "value": per_day.get(d, [0, 0])[0]} for d in days]
    fpy_per_day = [
        {"label": d.strftime("%d %b"),
         "value": round(100 * per_day[d][1] / per_day[d][0], 1) if d in per_day and per_day[d][0] else None}
        for d in days
    ]

    causes = (Unit.objects.filter(first_pass=False).exclude(reason="")
              .values("reason").annotate(n=Count("id")).order_by("-n")[:6])
    workload = (WorkOrder.objects.filter(status__in=[WorkOrder.ISSUED, WorkOrder.IN_PROGRESS, WorkOrder.QA],
                                         technician__isnull=False)
                .values("technician__name").annotate(m=Sum("est_minutes")).order_by("-m"))

    alerts = (
        [("bad", f"Order {o.number} overdue", f"{o.product.code} was due {o.due_date:%d %b}", o) for o in overdue]
        + [("warn", f"Order {o.number} due soon", f"{o.product.code} due {o.due_date:%d %b}", o) for o in due_soon]
        + [("info", f"Order {o.number} awaiting QA", f"{o.product.code} ready for team leader sign-off", o)
           for o in in_qa]
    )[:6]

    # Defect cost per week (Monday start) for the last 8 weeks
    this_monday = today - timedelta(days=today.weekday())
    weeks = [this_monday - timedelta(weeks=i) for i in range(7, -1, -1)]
    week_cost = {w: Decimal("0") for w in weeks}
    recent_defects = list(Defect.objects.select_related("product", "component").filter(
        occurred_at__date__gte=weeks[0]))
    for d in recent_defects:
        monday = timezone.localtime(d.occurred_at).date()
        monday -= timedelta(days=monday.weekday())
        if monday in week_cost:
            week_cost[monday] += d.cost
    month_defects = Defect.objects.filter(occurred_at__gte=views_defects.month_start())
    defect_kpi = {
        "count": month_defects.count(),
        "cost": sum((d.cost for d in month_defects), Decimal("0")),
    }

    return render(request, "mes/dashboard.html", {
        "kpis": {
            "open": len(open_orders), "overdue": len(overdue), "fpy": fpy,
            "tested": totals["tested"], "scrapped": totals["scrapped"], "in_qa": len(in_qa),
            "defects": defect_kpi,
        },
        "latest_defects": Defect.objects.select_related("product", "component")[:5],
        "alerts": alerts,
        "recent": Event.objects.select_related("work_order__product").order_by("-timestamp", "-id")[:8],
        "chart_data": {
            "status": status_data,
            "unitsPerDay": units_per_day,
            "fpyPerDay": fpy_per_day,
            "causes": [{"label": c["reason"], "value": c["n"]} for c in causes],
            "defectWeeks": [{"label": w.strftime("%d %b"), "value": float(c)} for w, c in week_cost.items()],
            "workload": [{"label": w["technician__name"], "value": w["m"] or 0} for w in workload],
        },
    })


def test_reports(request):
    reports = TestReport.objects.select_related("product", "technician").annotate(
        total=Count("steps"),
        passed_steps=Count("steps", filter=Q(steps__result="PASS")),
        failed_steps=Count("steps", filter=Q(steps__result="FAIL")),
    )
    q = request.GET.get("q", "").strip()
    result = request.GET.get("result", "")
    if q:
        reports = reports.filter(Q(serial__icontains=q) | Q(report_id__icontains=q)
                                 | Q(product__code__icontains=q) | Q(operator_name__icontains=q))
    if result in (TestReport.PASS, TestReport.FAIL):
        reports = reports.filter(overall_result=result)
    reports = list(reports)
    passed = sum(r.passed for r in reports)
    return render(request, "mes/test_reports.html", {
        "reports": reports, "q": q, "result": result,
        "stats": {"count": len(reports), "passed": passed, "failed": len(reports) - passed,
                  "rate": round(100 * passed / len(reports)) if reports else None},
    })


def test_report(request, pk):
    report = get_object_or_404(TestReport.objects.select_related("product", "technician", "unit__work_order"), pk=pk)
    sections = []
    for step in report.steps.all():
        if not sections or sections[-1]["name"] != step.section:
            sections.append({"name": step.section, "steps": []})
        sections[-1]["steps"].append(step)
    total = sum(len(s["steps"]) for s in sections)
    passed = sum(1 for s in sections for st in s["steps"] if st.result == "PASS")
    return render(request, "mes/test_report.html", {
        "report": report, "sections": sections, "total": total, "passed": passed,
        "failed": sum(1 for s in sections for st in s["steps"] if st.result == "FAIL"),
        "pct": round(100 * passed / total) if total else 0,
    })


def healthz(request):
    """Liveness and database check for the host's health monitor (no sign-in needed)."""
    from django.db import connection
    from django.http import JsonResponse
    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse({"status": "database unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
