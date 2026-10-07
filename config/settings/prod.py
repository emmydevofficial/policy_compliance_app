"""Production: the security checklist in SPEC section 13."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = env("SECRET_KEY")  # no default: refuse to start without one
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")

# HTTPS is on unless HTTPS_ENABLED=False, which is only for a short demonstration on a
# server with no domain name or certificate. Never turn it off for real use: without it,
# passwords and session cookies travel unencrypted.
HTTPS_ENABLED = env.bool("HTTPS_ENABLED", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=HTTPS_ENABLED)
SESSION_COOKIE_SECURE = HTTPS_ENABLED
CSRF_COOKIE_SECURE = HTTPS_ENABLED
CSRF_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000 if HTTPS_ENABLED else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# SMTP by default. A demonstration without a mail server can set
# EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend: notices are then written to
# the service log (journalctl) instead of being sent.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
if EMAIL_BACKEND.endswith("smtp.EmailBackend") and not EMAIL_HOST:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("EMAIL_HOST is required when sending email over SMTP.")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}

# HSTS preload is a domain-wide, slow-to-reverse commitment. It is off by default and
# switched on with SECURE_HSTS_PRELOAD=True once the client has decided; until then the
# check that asks for it is silenced deliberately, and only that one.
if not SECURE_HSTS_PRELOAD:
    SILENCED_SYSTEM_CHECKS = ["security.W021"]
