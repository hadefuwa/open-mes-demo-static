"""Roles and what each may do.

Roles are Django groups (created by a migration, assigned in the admin site or with `manage.py add_user`).
Anyone signed in can look at everything; the actions below need a role. When MES_REQUIRE_LOGIN is off (the
open demo) every action is allowed. Superusers may do anything.
"""
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied

PLANNER, TECHNICIAN, TEAM_LEADER, ADMIN = "Planner", "Technician", "Team leader", "Admin"
ROLES = [PLANNER, TECHNICIAN, TEAM_LEADER, ADMIN]

ACTIONS = {
    "stock": {PLANNER, TEAM_LEADER, ADMIN},                  # allocate and issue stock to a job
    "assign": {PLANNER, TEAM_LEADER, ADMIN},                 # assign a production technician
    "work": {TECHNICIAN, TEAM_LEADER, PLANNER, ADMIN},       # start, record units, retest, finish, log defects
    "qa": {TEAM_LEADER, ADMIN},                              # approve or reject at QA
    "raise": {PLANNER, ADMIN},                               # raise a works order from a customer order
    "machine": {PLANNER, TEAM_LEADER, ADMIN},                # change a machine's status
}


def role_names(user):
    return set(user.groups.values_list("name", flat=True)) if user.is_authenticated else set()


def allowed(user, action, names=None):
    if not settings.MES_REQUIRE_LOGIN:
        return True
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool((role_names(user) if names is None else names) & ACTIONS[action])


def require_role(action):
    """View decorator: 403 unless the user's role allows `action`."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not allowed(request.user, action):
                raise PermissionDenied(action)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
