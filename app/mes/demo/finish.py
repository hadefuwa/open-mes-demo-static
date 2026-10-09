"""The steps that follow loading data, shared by `seed` (which wipes first) and `load_real_data` (which never does)."""
from mes import bom_import, classify, pricing
from mes.models import Machine, ProductionTechnician, Workstation


def sync_basics(pack):
    """Make sure the pack's technicians, work areas and machines exist, without touching ones that do.
    Existing machines keep their current status, notes and location."""
    for name in getattr(pack, "TECHNICIANS", []):
        ProductionTechnician.objects.get_or_create(name=name)
    for name in getattr(pack, "STATIONS", []):
        Workstation.objects.get_or_create(name=name)
    for name, kind, status, location, notes in getattr(pack, "MACHINES", []):
        Machine.objects.get_or_create(name=name, defaults={"kind": kind, "status": status,
                                                           "location": location, "notes": notes})


def finish_catalogue(pack, command):
    """Classify items from structure and ERP types, then work out costs as the pack asks."""
    write = command.stdout.write
    kinds = classify.classify_kinds()
    if getattr(pack, "ESTIMATE_MISSING", True):  # real-data packs turn this off: never invent costs or routings
        filled, routed = bom_import.fill_missing_costs(), bom_import.ensure_routings()
    else:
        filled = routed = 0
    write(f"Classified: {kinds['finished']} products, {kinds['assembly']} assemblies, "
          f"{kinds['component']} components ({filled} costs estimated, {routed} routings added).")
    if getattr(pack, "CALIBRATE_TO_RRP", False):
        stats = pricing.calibrate_costs()
        write(f"Costs calibrated to RRP/3: {stats['topped_up']} BOMs topped up, {stats['made_leaf']} "
              f"made bought-in, {stats['estimated_rrp']} RRPs estimated.")
