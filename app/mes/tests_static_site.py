import json
import re
import tempfile
from io import StringIO
from pathlib import Path
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase


class StaticSiteTest(TestCase):
    """Builds the whole static site from the generic pack and checks it is self-contained and navigable."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("seed", pack="generic", force=True, stdout=StringIO())
        cls.tmp = tempfile.TemporaryDirectory()
        cls.site = Path(cls.tmp.name)
        call_command("build_static_site", out=str(cls.site), stdout=StringIO())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        super().tearDownClass()

    def pages(self):
        return sorted(self.site.rglob("*.html"))

    def test_settings_are_restored_after_the_build(self):
        self.assertFalse(settings.MES_STATIC_EXPORT)

    def test_every_page_links_only_to_files_that_exist(self):
        attr = re.compile(r'\b(?:href|src)="([^"]*)"')
        broken, checked = [], 0
        for page in self.pages():
            for raw in attr.findall(page.read_text(encoding="utf-8")):
                href = raw.replace("&amp;", "&")
                if not href or href.startswith(("#", "http://", "https://", "mailto:", "data:", "javascript:")):
                    continue
                self.assertFalse(href.startswith("/"), f"absolute link {href} in {page}")
                checked += 1
                if not (page.parent / unquote(urlsplit(href).path)).resolve().exists():
                    broken.append((str(page.relative_to(self.site)), href))
        self.assertGreater(checked, 1000)
        self.assertEqual(broken, [])

    def test_pages_are_read_only_and_self_contained(self):
        for page in self.pages():
            text = page.read_text(encoding="utf-8")
            self.assertNotIn("csrfmiddlewaretoken", text, page)
            self.assertNotIn('href="/admin', text, page)
            self.assertIn("static-demo.js", text, page)
        home = (self.site / "index.html").read_text(encoding="utf-8")
        self.assertIn("Static demo.", home)
        self.assertNotIn(">Admin<", home)

    def test_tables_work_in_the_browser_instead_of_on_a_server(self):
        products = (self.site / "products" / "index.html").read_text(encoding="utf-8")
        self.assertIn("data-static-table", products)
        self.assertIn("data-table-search", products)
        self.assertIn("data-table-csv", products)
        self.assertNotIn("?sort=", products)  # sorting links are replaced by click handlers
        self.assertNotIn("?format=csv", products)

    def test_forms_navigate_through_a_manifest_of_pre_rendered_pages(self):
        manifest = json.loads((self.site / "static-manifest.js").read_text(encoding="utf-8")
                              .split("=", 1)[1].rstrip().rstrip(";"))
        self.assertGreater(len(manifest["pages"]), 100)
        serial = next(iter(manifest["serials"].values()))
        key = f"/traceability/?serial={serial}"
        self.assertIn(key, manifest["pages"])
        self.assertTrue((self.site / manifest["pages"][key]).exists())
        # every GET form knows which page it belongs to, with a root-relative key
        keys = set()
        for page in self.pages():
            keys |= set(re.findall(r'data-key-path="([^"]*)"', page.read_text(encoding="utf-8")))
        self.assertTrue(keys and all(k.startswith("/") for k in keys), keys)

    def test_bom_exports_are_pre_rendered_as_csv_files(self):
        csvs = list(self.site.rglob("*.csv"))
        self.assertTrue(csvs)
        self.assertTrue(any("," in c.read_text(encoding="utf-8").splitlines()[0] for c in csvs))

    def test_crawl_is_bounded_and_the_timeline_does_not_run_away(self):
        shifted = [p for p in (self.site / "timeline").glob("index--shift-*.html")]
        self.assertLessEqual(len(shifted), 4)  # -8, -4, 4, 8 weeks
