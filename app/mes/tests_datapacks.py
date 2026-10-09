from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .datapacks import check_pack, load_pack
from .models import Product


class GenericPackTest(TestCase):
    """The generic pack is what a fresh clone of the project runs, so it must always work."""

    def test_pack_data_is_consistent(self):
        self.assertEqual(check_pack(load_pack("generic")), [])

    def test_check_pack_reports_typos(self):
        class Bad:
            FINISHED = [("A1", "Thing"), ("A1", "Duplicate")]
            ASSEMBLIES, COMPONENTS = [], [("C1", "Part", "X", "1.00")]
            BOM = {"A1": [("C1", 2), ("NOPE", 1)]}
            MACHINES = [("Mill", "k", "available", "", "")]
            ROUTINGS = {"A1": [("Cut", "Lathe", 5)]}
            LIVE_ORDERS = [("1", "A1", 1, "Nowhere", 1, "bogus", "Zed", 10)]
            TECHNICIANS, STATIONS = ["Alex"], ["Bay"]
            HOOKS = ("nonsense",)

        problems = "\n".join(check_pack(Bad))
        for expected in ("duplicate product code A1", "unknown product NOPE", "unknown machine Lathe",
                         "unknown station Nowhere", "unknown technician Zed", "unknown status bogus",
                         "unknown hook nonsense"):
            self.assertIn(expected, problems)

    def test_seeding_from_scratch_and_every_page_renders(self):
        out = StringIO()
        call_command("seed", pack="generic", force=True, stdout=out)
        self.assertIn("Data pack: generic", out.getvalue())
        self.assertEqual(Product.objects.filter(kind=Product.FINISHED).count(), 8)

        finished = Product.objects.get(code="FG1001")
        component = Product.objects.filter(kind=Product.COMPONENT).first()
        urls = [reverse(n) for n in ("dashboard", "board", "products", "assemblies", "components", "machines",
                                     "timeline", "defects", "customer_orders", "test_reports", "traceability",
                                     "data_browser", "my_jobs")]
        urls += [finished.get_absolute_url(), reverse("bom", args=[finished.pk]), component.get_absolute_url(),
                 reverse("data_table", args=["product"])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_generic_pack_has_no_business_specific_data(self):
        import inspect
        source = inspect.getsource(load_pack("generic")).lower()
        for word in ("matrix", "locktronics", "smart factory", "haas", "boxford"):
            self.assertNotIn(word, source)
