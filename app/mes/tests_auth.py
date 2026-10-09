from datetime import date
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Event, Product, WorkOrder


@override_settings(MES_REQUIRE_LOGIN=True)
class RolesAndLoginTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        product = Product.objects.create(code="FG1", name="Thing", kind=Product.FINISHED)
        cls.order = WorkOrder.objects.create(number="1", product=product, quantity=2, due_date=date.today())
        cls.users = {}
        for username, role in [("pat", "Planner"), ("tess", "Technician"), ("lee", "Team leader"), ("view", None)]:
            user = User.objects.create_user(username, password="correct-horse-battery")
            if role:
                user.groups.add(Group.objects.get(name=role))
            cls.users[username] = user

    def login(self, username):
        self.client.force_login(self.users[username])

    def post(self, name, *args):
        return self.client.post(reverse(name, args=args))

    def status(self):
        self.order.refresh_from_db()
        return self.order.status

    def test_roles_exist_after_migration(self):
        self.assertEqual(set(Group.objects.values_list("name", flat=True)),
                         {"Planner", "Technician", "Team leader", "Admin"})

    def test_anonymous_visitors_are_sent_to_sign_in(self):
        for url in (reverse("dashboard"), reverse("board"), reverse("operator", args=[self.order.pk])):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith("/login/?next="), response["Location"])
        self.assertEqual(self.client.post(reverse("allocate", args=[self.order.pk])).status_code, 302)

    def test_sign_in_page_health_check_and_admin_login_stay_open(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        self.assertEqual(self.client.get(reverse("healthz")).json(), {"status": "ok"})
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)

    def test_signing_in_works_and_wrong_password_is_refused(self):
        bad = self.client.post(reverse("login"), {"username": "pat", "password": "wrong"})
        self.assertContains(bad, "did not match")
        good = self.client.post(reverse("login"), {"username": "pat", "password": "correct-horse-battery"})
        self.assertRedirects(good, "/", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_sign_out(self):
        self.login("pat")
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_a_viewer_can_look_but_not_act(self):
        self.login("view")
        self.assertEqual(self.client.get(reverse("operator", args=[self.order.pk])).status_code, 200)
        for action in ("allocate", "issue", "assign", "start", "finish", "approve", "reject"):
            self.assertEqual(self.post(action, self.order.pk).status_code, 403, action)
        self.assertEqual(self.status(), WorkOrder.ENTERED)

    def test_each_role_can_do_its_own_steps_only(self):
        pk = self.order.pk
        self.login("tess")  # technician: cannot allocate
        self.assertEqual(self.post("allocate", pk).status_code, 403)
        self.login("pat")   # planner: allocates and issues, but cannot approve QA
        self.assertEqual(self.post("allocate", pk).status_code, 302)
        self.assertEqual(self.post("issue", pk).status_code, 302)
        self.assertEqual(self.status(), WorkOrder.ISSUED)
        self.assertEqual(self.post("approve", pk).status_code, 403)
        self.login("tess")  # technician: starts the job
        self.assertEqual(self.post("start", pk).status_code, 302)
        self.assertEqual(self.status(), WorkOrder.IN_PROGRESS)
        WorkOrder.objects.filter(pk=pk).update(status=WorkOrder.QA)
        self.assertEqual(self.post("approve", pk).status_code, 403)  # technician cannot sign off QA
        self.login("lee")   # team leader can
        self.assertEqual(self.post("approve", pk).status_code, 302)
        self.assertEqual(self.status(), WorkOrder.COMPLETE)

    def test_buttons_are_hidden_from_roles_that_cannot_use_them(self):
        self.login("view")
        page = self.client.get(reverse("operator", args=[self.order.pk])).content.decode()
        self.assertNotIn(reverse("allocate", args=[self.order.pk]), page)
        self.login("pat")
        page = self.client.get(reverse("operator", args=[self.order.pk])).content.decode()
        self.assertIn(reverse("allocate", args=[self.order.pk]), page)

    def test_events_record_who_did_it(self):
        self.login("pat")
        self.post("allocate", self.order.pk)
        self.assertEqual(Event.objects.get(work_order=self.order, action="stock allocated").actor, "pat")

    def test_superusers_can_do_everything(self):
        boss = User.objects.create_superuser("boss", password="correct-horse-battery")
        self.client.force_login(boss)
        self.assertEqual(self.post("allocate", self.order.pk).status_code, 302)
        self.assertEqual(self.post("approve", self.order.pk).status_code, 302)  # allowed (nothing happens: not in QA)


class OpenDemoModeTest(TestCase):
    """With login off (the default) nothing changes: the demo stays open."""

    def test_no_login_needed_and_every_action_is_allowed(self):
        product = Product.objects.create(code="FG1", name="Thing", kind=Product.FINISHED)
        order = WorkOrder.objects.create(number="1", product=product, quantity=1)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(self.client.post(reverse("allocate", args=[order.pk])).status_code, 302)
        self.assertEqual(Event.objects.get(action="stock allocated").actor, "")


class AddUserCommandTest(TestCase):
    def test_creates_a_user_with_roles_and_a_generated_password(self):
        out = StringIO()
        call_command("add_user", "sam", "--role", "technician", "--role", "planner", "--name", "Sam Jones", stdout=out)
        user = User.objects.get(username="sam")
        self.assertEqual(set(user.groups.values_list("name", flat=True)), {"Technician", "Planner"})
        self.assertEqual((user.first_name, user.last_name), ("Sam", "Jones"))
        self.assertIn("Initial password:", out.getvalue())
        self.assertTrue(user.has_usable_password())

    def test_adding_a_role_to_an_existing_user_keeps_the_password(self):
        call_command("add_user", "sam", "--role", "technician", "--password", "keep-this-password-1", stdout=StringIO())
        call_command("add_user", "sam", "--role", "team-leader", stdout=StringIO())
        user = User.objects.get(username="sam")
        self.assertTrue(user.check_password("keep-this-password-1"))
        self.assertEqual(user.groups.count(), 2)


class SeedSafetyTest(TestCase):
    def test_seed_refuses_to_wipe_without_force_when_debug_is_off(self):
        with self.assertRaisesMessage(CommandError, "WIPES the database"):
            call_command("seed", pack="generic", stdout=StringIO())  # tests run with DEBUG off
