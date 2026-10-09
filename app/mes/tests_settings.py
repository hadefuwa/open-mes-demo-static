import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

APP_DIR = Path(__file__).resolve().parents[1]
SNIPPET = (
    "import json, config.settings as s;"
    "print(json.dumps({k: getattr(s, k, None) for k in ['DEBUG','ALLOWED_HOSTS','CSRF_TRUSTED_ORIGINS',"
    "'SECURE_SSL_REDIRECT','SESSION_COOKIE_SECURE','CSRF_COOKIE_SECURE','SECURE_HSTS_SECONDS','MES_REQUIRE_LOGIN',"
    "'TIME_ZONE']} | {'engine': s.DATABASES['default']['ENGINE'], 'cursors': s.DATABASES['default'].get('DISABLE_SERVER_SIDE_CURSORS')}))"
)


def load_settings(**env):
    """Import the settings module in a clean process with only the given environment, as a host would."""
    clean = {k: v for k, v in os.environ.items()
             if k not in ("DEBUG", "SECRET_KEY", "DATABASE_URL", "ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS", "MES_REQUIRE_LOGIN",
                          "RENDER_EXTERNAL_HOSTNAME", "TIME_ZONE", "SECURE_SSL_REDIRECT", "MES_DB")}
    return subprocess.run([sys.executable, "-c", SNIPPET], cwd=APP_DIR, env={**clean, **env}, capture_output=True, text=True)


class SettingsFromEnvironmentTest(SimpleTestCase):
    def test_local_defaults_are_a_convenient_development_setup(self):
        result = load_settings()
        self.assertEqual(result.returncode, 0, result.stderr)
        s = json.loads(result.stdout)
        self.assertTrue(s["DEBUG"])
        self.assertFalse(s["MES_REQUIRE_LOGIN"])
        self.assertIn("sqlite", s["engine"])
        self.assertFalse(s["SECURE_SSL_REDIRECT"] or False)

    def test_production_refuses_to_start_with_the_development_secret_key(self):
        result = load_settings(DEBUG="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_production_is_hardened_and_uses_postgres_and_login(self):
        result = load_settings(DEBUG="0", SECRET_KEY="x" * 60, MES_REQUIRE_LOGIN="1", TIME_ZONE="Europe/London",
                               ALLOWED_HOSTS="mes.example.com, other.example.com",
                               DATABASE_URL="postgresql://u:p@db.example.com:6543/postgres?sslmode=require")
        self.assertEqual(result.returncode, 0, result.stderr)
        s = json.loads(result.stdout)
        self.assertFalse(s["DEBUG"])
        self.assertTrue(s["MES_REQUIRE_LOGIN"])
        self.assertTrue(s["SECURE_SSL_REDIRECT"])
        self.assertTrue(s["SESSION_COOKIE_SECURE"] and s["CSRF_COOKIE_SECURE"])
        self.assertGreater(s["SECURE_HSTS_SECONDS"], 0)
        self.assertEqual(s["ALLOWED_HOSTS"], ["mes.example.com", "other.example.com"])
        self.assertEqual(s["TIME_ZONE"], "Europe/London")
        self.assertTrue(s["engine"].endswith("postgresql"))
        self.assertTrue(s["cursors"])  # required behind Supabase's transaction pooler

    def test_render_hostname_is_trusted_automatically(self):
        result = load_settings(DEBUG="0", SECRET_KEY="x" * 60, RENDER_EXTERNAL_HOSTNAME="open-mes.onrender.com")
        s = json.loads(result.stdout)
        self.assertIn("open-mes.onrender.com", s["ALLOWED_HOSTS"])
        self.assertIn("https://open-mes.onrender.com", s["CSRF_TRUSTED_ORIGINS"])
