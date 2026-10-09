import importlib
import random
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from mes.datapacks import check_pack, load_pack
from mes.demo.builder import build_catalogue
from mes.demo.finish import finish_catalogue
from mes.models import (BomLine, CustomerOrder, CustomerOrderLine, Defect, Event, Machine, Product,
                        ProductionTechnician, RoutingStep, TestReport, TestStep, Unit, WorkOrder,
                        Workstation)


class Command(BaseCommand):
    help = "Reset the database and load a data pack (default: the MES_DATA_PACK setting, 'generic')."

    def add_arguments(self, parser):
        parser.add_argument("--pack", help="data pack in mes/datapacks to load")
        parser.add_argument("--force", action="store_true",
                            help="wipe the database even though DEBUG is off or it is not SQLite")

    def handle(self, *args, pack=None, force=False, **options):
        if not force and (not settings.DEBUG or connection.vendor != "sqlite"):
            raise CommandError(
                f"seed WIPES the database ({connection.vendor}, DEBUG={settings.DEBUG}). Refusing to run against "
                "what may be a production database; pass --force if you really mean it.")
        pack = load_pack(pack)
        self.stdout.write(f"Data pack: {pack.__name__.rsplit('.', 1)[-1]}")
        problems = check_pack(pack)
        if problems:
            raise CommandError("The data pack has problems:\n  " + "\n  ".join(problems))
        for model in (Event, Defect, TestStep, TestReport, Unit, CustomerOrderLine, CustomerOrder, WorkOrder,
                      RoutingStep, BomLine, Machine, Product, Workstation, ProductionTechnician):
            model.objects.all().delete()

        products, machines = build_catalogue(pack)
        stations = {n: Workstation.objects.create(name=n) for n in pack.STATIONS}
        technicians = {n: ProductionTechnician.objects.create(name=n) for n in pack.TECHNICIANS}
        today = date.today()
        live_orders = getattr(pack, "LIVE_ORDERS", [])

        orders = {}
        for num, code, qty, station, days, status, who, minutes in live_orders:
            orders[num] = WorkOrder.objects.create(
                number=num, product=products[code], quantity=qty, workstation=stations[station],
                due_date=today + timedelta(days=days), start_date=today + timedelta(days=days - max(1, qty // 4)),
                status=status, est_minutes=minutes, technician=technicians.get(who),
                printed=status in (WorkOrder.ISSUED, WorkOrder.IN_PROGRESS, WorkOrder.QA))

        rng = random.Random(42)  # deterministic demo data
        serial_counter = {}
        causes = ["Loose connection", "Solder bridge on PCB", "Scratched panel",
                  "Wrong fastener fitted", "Failed pressure test", "Sensor misaligned"]
        cause_weights = [6, 5, 4, 3, 2, 2]

        def stamp(obj, when):
            type(obj).objects.filter(pk=obj.pk).update(**{
                "timestamp" if isinstance(obj, Event) else "created_at": when})

        def log(order, action, when, detail="", unit=None):
            stamp(Event.objects.create(work_order=order, unit=unit, action=action, detail=detail), when)

        def build_units(order, count, when):
            """Record `count` units on an order, with realistic first-pass / rework / scrap mix."""
            code = order.product.code
            for _ in range(count):
                serial_counter[code] = serial_counter.get(code, 0) + 1
                serial = f"{code}-{serial_counter[code]:04d}"
                when = when + timedelta(minutes=rng.randint(8, 25))
                roll = rng.random()
                if roll < 0.82:
                    result, reason, first = Unit.PASS, "", True
                elif roll < 0.95:
                    result, reason, first = Unit.PASS, rng.choices(causes, cause_weights)[0], False
                else:
                    result, reason, first = Unit.SCRAP, rng.choices(causes, cause_weights)[0], False
                unit = Unit.objects.create(work_order=order, serial=serial, result=result,
                                           reason=reason, first_pass=first)
                stamp(unit, when)
                log(order, "unit recorded", when, "pass" if first else f"rework: {reason}", unit)
                if not first and result == Unit.PASS:
                    log(order, "unit retested", when + timedelta(minutes=12), "pass", unit)
            return when

        history_products = getattr(pack, "HISTORY_PRODUCTS", [])
        if history_products:
            # Two weeks of history: completed orders on working days.
            history_no = getattr(pack, "HISTORY_START_NUMBER", 1000)
            history_stations = getattr(pack, "HISTORY_STATIONS", list(stations))
            for back in range(14, 0, -1):
                day = today - timedelta(days=back)
                if day.weekday() >= 5:
                    continue
                for _ in range(rng.choice([1, 2, 2])):
                    code = rng.choice(history_products)
                    qty = rng.randint(3, 8)
                    order = WorkOrder.objects.create(
                        number=str(history_no), product=products[code], quantity=qty,
                        workstation=stations[rng.choice(history_stations)],
                        technician=technicians[rng.choice(list(technicians))], due_date=day, start_date=day,
                        status=WorkOrder.COMPLETE, est_minutes=qty * 20, printed=True)
                    history_no -= 1
                    start = timezone.make_aware(datetime.combine(day, time(8, rng.randint(0, 40))))
                    log(order, "started", start)
                    end = build_units(order, qty, start)
                    log(order, "sent to QA", end + timedelta(minutes=5))
                    log(order, "QA approved, completed", end + timedelta(minutes=30))

        # Live orders: those in progress are part-built, those in QA are waiting for sign-off.
        now = timezone.now()
        for order in orders.values():
            if order.status == WorkOrder.IN_PROGRESS:
                log(order, "started", now - timedelta(hours=3))
                build_units(order, max(1, order.quantity * 4 // 10), now - timedelta(hours=3))
            elif order.status == WorkOrder.QA:
                log(order, "started", now - timedelta(hours=5))
                build_units(order, order.quantity, now - timedelta(hours=5))
                log(order, "sent to QA", now - timedelta(minutes=20))

        customer_orders = getattr(pack, "CUSTOMER_ORDERS", [])
        for number, days_ago, customer, ref, lines in customer_orders:
            order = CustomerOrder.objects.create(
                number=number, order_date=today - timedelta(days=days_ago), customer=customer,
                ship_date=today - timedelta(days=days_ago) + timedelta(days=21), customer_ref=ref)
            for code, qty in lines:
                CustomerOrderLine.objects.create(order=order, product=products[code], quantity=qty)

        # Real data (workbooks etc.) if the pack has any, then kinds and costs worked out from structure.
        if hasattr(pack, "load_real_data"):
            pack.load_real_data(self)
        finish_catalogue(pack, self)
        products = {p.code: p for p in Product.objects.all()}

        # Per-area extra demo data (sales history, planning, machines, defects), as the pack requests.
        ctx = SimpleNamespace(today=today, rng=random.Random(7), products=products, machines=machines,
                              stations=stations, technicians=technicians, orders=orders, pack=pack)
        for area in getattr(pack, "HOOKS", ()):
            importlib.import_module(f"mes.demo.{area}").seed(ctx)

        self.stdout.write(self.style.SUCCESS(
            "Seeded %d products, %d work orders (%d completed), %d units, %d customer orders." % (
                Product.objects.count(), WorkOrder.objects.count(),
                WorkOrder.objects.filter(status=WorkOrder.COMPLETE).count(),
                Unit.objects.count(), CustomerOrder.objects.count())))
