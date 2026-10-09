"""Django settings for Open-MES.

Configuration comes from environment variables, so the same code runs on a laptop (SQLite, debug on, no
login) and in production (PostgreSQL, debug off, login required). See Docs/DEPLOY.md and .env.example.
"""
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def env_list(name):
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# --- core -----------------------------------------------------------------------------------------------

DEV_SECRET_KEY = 'django-insecure-o+4#d_2ls3%xv6_on$-*o9lsn_n72ug0a+ihes7&+llq79f0^m'
DEBUG = env_bool("DEBUG", True)
SECRET_KEY = os.environ.get("SECRET_KEY", DEV_SECRET_KEY)
if not DEBUG and SECRET_KEY == DEV_SECRET_KEY:
    raise ImproperlyConfigured("Set the SECRET_KEY environment variable when DEBUG is off.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")  # set automatically on Render
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_HOST}")

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'mes',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'mes.middleware.AuditUser',
    'mes.middleware.LoginRequired',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'mes.context.alerts',
                'mes.context.breadcrumbs',
                'mes.context.project',
                'mes.context.access',
                'mes.context.static_export',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# --- database -------------------------------------------------------------------------------------------
# DATABASE_URL (e.g. a Supabase PostgreSQL URL) wins; otherwise SQLite. MES_DB points SQLite elsewhere.

if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=600, conn_health_checks=True)}
    if DATABASES["default"]["ENGINE"].endswith("postgresql"):
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True  # needed behind Supabase's transaction pooler
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.environ.get('MES_DB') or BASE_DIR / 'db.sqlite3',
        }
    }

# --- authentication -------------------------------------------------------------------------------------
# Off by default so the demo and tests are open; production sets MES_REQUIRE_LOGIN=1.

MES_REQUIRE_LOGIN = env_bool("MES_REQUIRE_LOGIN", False)
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", 60 * 60 * 12))  # one shift

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- internationalisation -------------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# --- static files ---------------------------------------------------------------------------------------

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- production hardening (only when DEBUG is off) ------------------------------------------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # the host terminates TLS and forwards this
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]  # health checks arrive over plain HTTP
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", 3600))
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"django.request": {"handlers": ["console"], "level": "ERROR"}},
}

# --- Open-MES -------------------------------------------------------------------------------------------

# Labour cost per hour, used to turn build minutes into cost
MES_LABOUR_RATE_PER_HOUR = float(os.environ.get("MES_LABOUR_RATE_PER_HOUR", 28))

# Which data pack `manage.py seed` loads (see mes/datapacks), and where real source workbooks live.
MES_DATA_PACK = os.environ.get("MES_DATA_PACK", "generic")
MES_DATA_DIR = Path(os.environ.get("MES_DATA_DIR") or BASE_DIR.parent / "data")

# Where "GitHub" links in the UI point (each repository sets its own).
MES_PROJECT_URL = os.environ.get("MES_PROJECT_URL", "https://github.com/hadefuwa/open-mes-demo-static")

# Set only by `manage.py build_static_site`: renders pages for the read-only static copy of the demo.
MES_STATIC_EXPORT = False
