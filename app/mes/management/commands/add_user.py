import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from mes.permissions import ADMIN, PLANNER, ROLES, TEAM_LEADER, TECHNICIAN

CHOICES = {"planner": PLANNER, "technician": TECHNICIAN, "team-leader": TEAM_LEADER, "admin": ADMIN}


class Command(BaseCommand):
    help = ("Create a user (or add roles to an existing one). Roles: planner, technician, team-leader, admin. "
            "For a full administrator who can use the admin site, use createsuperuser instead.")

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", action="append", choices=sorted(CHOICES), required=True,
                            help="a role to give the user; repeat for several")
        parser.add_argument("--name", default="", help="full name")
        parser.add_argument("--email", default="")
        parser.add_argument("--password", help="initial password (a random one is generated and shown if omitted)")

    def handle(self, *args, username, role, name, email, password, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username)
        generated = None
        if created or password:
            generated = None if password else secrets.token_urlsafe(12)
            user.set_password(password or generated)
        if name:
            first, _, last = name.partition(" ")
            user.first_name, user.last_name = first, last
        if email:
            user.email = email
        user.save()
        for key in role:
            group, _ = Group.objects.get_or_create(name=CHOICES[key])
            user.groups.add(group)
        roles = ", ".join(sorted(user.groups.values_list("name", flat=True)))
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} {username} ({roles})."))
        if generated:
            self.stdout.write(f"Initial password: {generated}\nAsk them to change it after signing in.")
