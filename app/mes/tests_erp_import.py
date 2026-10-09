import os
import tempfile
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from . import bom_import, classify
from .models import BomLine, Machine, Product, ProductionTechnician, WorkOrder, Workstation


def make_register(path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bill of Materials"
    ws.append(["Bom Reference", "Description", "Type", "Category", "Revision", "Unit Cost", "Category Name"])
    ws.append(["FG1", "Widget", "Finished Goods", 2, "", 100.5, "Widgets"])
    ws.append(["SA1", "Sub board", "Sub-Assembly", 90, "V1", 20, ""])
    ws.append(["CP1", "Bought part", "Component", 10, "", 0, ""])
    ws.append(["VL1", "Valve, 3/2, button", "Finished Goods", 4, "", 12, ""])  # sounds like a part, ERP says product
    ws.append([None, "row without a reference", "Component", None, None, 1, None])
    wb.save(path)


def make_stock(path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock Records"
    ws.append(["Stock Code", "Description", "Category", "Item Type", "Quantity in Stock"])
    ws.append(["CP1", "Bought part (stock name)", 10, "Stock Item", 5])
    ws.append(["NEW1", "Fresh part", 10, "Non-Stock Item", 0])
    ws.append(["SA1", "Sub board", 90, "Stock Item", 3.5])
    wb.save(path)


class RegisterAndStockImportTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.register = os.path.join(self.tmp.name, "register.xlsx")
        self.stock = os.path.join(self.tmp.name, "stock.xlsx")
        make_register(self.register)
        make_stock(self.stock)

    def test_register_sets_erp_type_cost_and_range(self):
        summary = bom_import.import_workbook(self.register)
        self.assertEqual((summary["register_created"], summary["register_updated"]), (4, 0))
        fg = Product.objects.get(code="FG1")
        self.assertEqual((fg.erp_type, fg.standard_cost, fg.range_name, fg.name), ("Finished Goods", Decimal("100.5"), "Widgets", "Widget"))
        self.assertEqual(fg.unit_cost, Decimal("100.5"))  # no imported structure, so the standard cost is its cost
        self.assertEqual(Product.objects.get(code="SA1").revision, "V1")
        self.assertIsNone(Product.objects.get(code="CP1").standard_cost)  # a zero cost means unknown
        self.assertEqual(bom_import.import_workbook(self.register)["register_updated"], 4)  # re-import updates, never duplicates
        self.assertEqual(Product.objects.count(), 4)

    def test_items_with_an_imported_bom_keep_their_rolled_up_cost(self):
        part = Product.objects.create(code="CP9", name="Part", kind=Product.COMPONENT, unit_cost=Decimal("10"))
        fg = Product.objects.create(code="FG1", name="Old name", kind=Product.FINISHED)
        BomLine.objects.create(parent=fg, child=part, quantity=3)
        bom_import.import_workbook(self.register)
        fg.refresh_from_db()
        self.assertIsNone(fg.unit_cost)                          # cost still comes from the BOM
        self.assertEqual(fg.standard_cost, Decimal("100.5"))
        self.assertEqual(fg.name, "Widget")                      # the ERP's description wins
        self.assertEqual(fg.cost_variance, Decimal("70.5"))      # ERP 100.50 vs BOM roll-up 30.00

    def test_stock_records_set_on_hand_and_stocked_flag(self):
        Product.objects.create(code="CP1", name="Bought part", kind=Product.COMPONENT)
        summary = bom_import.import_workbook(self.stock)
        self.assertEqual((summary["records_created"], summary["records_updated"]), (2, 1))
        cp = Product.objects.get(code="CP1")
        self.assertEqual((cp.stock_quantity, cp.is_stocked, cp.name), (Decimal("5"), True, "Bought part"))
        new = Product.objects.get(code="NEW1")
        self.assertEqual((new.kind, new.is_stocked, new.stock_quantity), (Product.COMPONENT, False, Decimal("0")))
        self.assertEqual(Product.objects.get(code="SA1").stock_quantity, Decimal("3.5"))

    def test_erp_type_beats_guesswork_in_classification(self):
        bom_import.import_workbook(self.register)
        Product.objects.filter(code="VL1").update(rrp=Decimal("50"))  # cheap and valve-like: heuristics would say part
        classify.classify_kinds()
        kinds = {p.code: p.kind for p in Product.objects.all()}
        self.assertEqual(kinds, {"FG1": Product.FINISHED, "SA1": Product.ASSEMBLY, "CP1": Product.COMPONENT,
                                 "VL1": Product.FINISHED})

    def test_low_stock_prefers_on_hand_over_free_stock(self):
        p = Product(code="X", name="X", free_stock=100, reorder_level=10, stock_quantity=Decimal("4"))
        self.assertTrue(p.low_stock)
        p.stock_quantity = None
        self.assertFalse(p.low_stock)


class LoadRealDataCommandTest(TestCase):
    """load_real_data refreshes data from files without ever deleting what people have entered."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        make_register(os.path.join(self.tmp.name, "register.xlsx"))
        make_stock(os.path.join(self.tmp.name, "stock.xlsx"))
        folder = self.tmp.name

        def load(command):
            for name in ("register.xlsx", "stock.xlsx"):
                bom_import.import_workbook(os.path.join(folder, name))

        self.pack = SimpleNamespace(
            __name__="mes.datapacks.testpack", TECHNICIANS=["Alex"], STATIONS=["Bay 1"],
            MACHINES=[("Mill", "Milling", "available", "Shop", "")], ESTIMATE_MISSING=False, load_real_data=load)

    def run_command(self):
        out = StringIO()
        with mock.patch("mes.management.commands.load_real_data.load_pack", return_value=self.pack):
            call_command("load_real_data", stdout=out)
        return out.getvalue()

    def test_nothing_that_people_entered_is_deleted(self):
        product = Product.objects.create(code="MINE", name="Entered by hand", kind=Product.FINISHED)
        order = WorkOrder.objects.create(number="9001", product=product, quantity=1)
        user = User.objects.create_user("pat", password="x" * 12)
        Machine.objects.create(name="Mill", kind="Milling", status=Machine.DOWN, notes="Spindle broken")
        self.run_command()
        self.assertTrue(Product.objects.filter(code="MINE").exists())
        self.assertTrue(WorkOrder.objects.filter(pk=order.pk).exists())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        mill = Machine.objects.get(name="Mill")
        self.assertEqual((mill.status, mill.notes), (Machine.DOWN, "Spindle broken"))  # not reset to the pack's value

    def test_basics_are_created_and_a_second_run_changes_nothing(self):
        first = self.run_command()
        self.assertIn("nothing is deleted", first)
        self.assertTrue(ProductionTechnician.objects.filter(name="Alex").exists())
        self.assertTrue(Workstation.objects.filter(name="Bay 1").exists())
        self.assertEqual(Machine.objects.get(name="Mill").status, Machine.AVAILABLE)
        counts = (Product.objects.count(), Machine.objects.count(), ProductionTechnician.objects.count())
        self.run_command()
        self.assertEqual((Product.objects.count(), Machine.objects.count(), ProductionTechnician.objects.count()), counts)
        self.assertEqual(Product.objects.get(code="FG1").kind, Product.FINISHED)  # classified from the ERP type

    def test_a_pack_without_a_loader_is_refused(self):
        self.pack = SimpleNamespace(__name__="mes.datapacks.demo")
        with self.assertRaisesMessage(Exception, "no load_real_data"):
            self.run_command()
