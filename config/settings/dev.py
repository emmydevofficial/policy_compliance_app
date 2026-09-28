"""Local development: DEBUG on, console email, local SQLite database."""

from .base import *  # noqa: F403
from .base import INSTALLED_APPS, MIDDLEWARE, env

DEBUG = True
SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-key-not-for-production")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Never send real email from a development environment.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
ALLOW_REAL_EMAIL = False

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

if env.bool("DEBUG_TOOLBAR", default=True):
    try:
        import debug_toolbar  # noqa: F401

        INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
        MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware", *MIDDLEWARE]
        INTERNAL_IPS = ["127.0.0.1"]
    except ImportError:
        pass
