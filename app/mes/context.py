from django.conf import settings
from django.urls import reverse

from .models import (CustomerOrder, Machine, Product, TestReport, WorkOrder)


def alerts(request):
    """Count of overdue orders, shown on the top-bar bell."""
    open_orders = WorkOrder.objects.exclude(status=WorkOrder.COMPLETE).filter(due_date__isnull=False)
    return {"alert_count": sum(1 for o in open_orders if o.is_overdue)}


# url_name -> (section, section url name, page label). The last crumb is the page itself.
_PAGES = {
    "products": ("Catalogue", "Products"),
    "assemblies": ("Catalogue", "Assemblies"),
    "components": ("Catalogue", "Components"),
    "board": ("Production", "Work orders"),
    "my_jobs": ("Production", "My jobs"),
    "timeline": ("Production", "Planning timeline"),
    "machines": ("Production", "Machines"),
    "customer_orders": ("Sales", "Customer orders"),
    "test_reports": ("Quality", "Test reports"),
    "defects": ("Quality", "Defects"),
    "traceability": ("Quality", "Traceability"),
    "data_browser": ("System", "Data browser"),
}


def breadcrumbs(request):
    """Trail like Catalogue > Products > FG1001 > Bill of materials, built from the URL."""
    match = getattr(request, "resolver_match", None)
    if not match or match.url_name in (None, "dashboard"):
        return {"breadcrumbs": []}
    name, kw = match.url_name, match.kwargs
    trail = [("Dashboard", reverse("dashboard"))]

    def page(url_name):
        section, label = _PAGES[url_name]
        trail.extend([(section, ""), (label, reverse(url_name))])

    if name in _PAGES:
        section, label = _PAGES[name]
        trail.extend([(section, ""), (label, "")])
    elif name in ("product_detail", "bom", "component_detail"):
        product = Product.objects.filter(pk=kw["pk"]).first()
        if product:
            page({"assembly": "assemblies", "component": "components"}.get(product.kind, "products"))
            if name == "bom":
                trail.extend([(product.code, product.get_absolute_url()), ("Bill of materials", "")])
            else:
                trail.append((product.code, ""))
    elif name == "operator":
        order = WorkOrder.objects.filter(pk=kw["pk"]).first()
        if order:
            page("board")
            trail.append((f"Work order {order.number}", ""))
    elif name == "customer_order":
        order = CustomerOrder.objects.filter(pk=kw["pk"]).first()
        if order:
            page("customer_orders")
            trail.append((f"Order {order.number}", ""))
    elif name == "machine_detail":
        machine = Machine.objects.filter(pk=kw["pk"]).first()
        if machine:
            page("machines")
            trail.append((machine.name, ""))
    elif name == "test_report":
        report = TestReport.objects.filter(pk=kw["pk"]).first()
        if report:
            page("test_reports")
            trail.append((report.report_id, ""))
    elif name == "data_table":
        page("data_browser")
        trail.append((kw["model_name"], ""))
    else:
        return {"breadcrumbs": []}
    return {"breadcrumbs": trail}


def static_export(request):
    """True while building the static GitHub Pages copy of the demo (see build_static_site)."""
    return {"static_export": bool(getattr(settings, "MES_STATIC_EXPORT", False))}


def project(request):
    """The repository URL shown in the footer."""
    return {"project_url": getattr(settings, "MES_PROJECT_URL", "")}
