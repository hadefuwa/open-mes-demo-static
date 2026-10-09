from contextvars import ContextVar

from django.conf import settings
from django.contrib.auth.views import redirect_to_login

# The signed-in user for the request being handled, so code far from the view (like Event.save) can record who did something.
current_user = ContextVar("mes_current_user", default=None)

# Reachable without signing in: the sign-in page, the admin's own sign-in, health checks and static files.
OPEN_PREFIXES = ("/login/", "/admin/", "/healthz", "/static/")


class AuditUser:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user if request.user.is_authenticated else None
        token = current_user.set(user)
        try:
            return self.get_response(request)
        finally:
            current_user.reset(token)


class LoginRequired:
    """Send anonymous visitors to the sign-in page when MES_REQUIRE_LOGIN is on (checked per request)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (settings.MES_REQUIRE_LOGIN and not request.user.is_authenticated
                and not request.path.startswith(OPEN_PREFIXES)):
            return redirect_to_login(request.get_full_path())
        return self.get_response(request)
