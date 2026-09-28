from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.urls import resolve
from django.urls.exceptions import Resolver404

from .permissions import EXECUTIVE, SAFE_METHODS

# Endpoints an executive may POST to: they concern the executive's own session and
# credentials, not any data in the application.
EXECUTIVE_POST_ALLOWED = {"accounts:logout", "accounts:password_change"}


class ExecutiveReadOnlyMiddleware:
    """SPEC 2, rule 3: an EXECUTIVE receives 403 on every write, whatever the view says."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "role", None) == EXECUTIVE
            and request.method not in SAFE_METHODS
        ):
            try:
                name = resolve(request.path_info).view_name
            except Resolver404:
                name = ""
            if name not in EXECUTIVE_POST_ALLOWED:
                raise PermissionDenied
        return self.get_response(request)


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        policy = getattr(settings, "CONTENT_SECURITY_POLICY", {})
        self.header = "; ".join(f"{k} {' '.join(v)}" for k, v in policy.items())

    def __call__(self, request):
        response = self.get_response(request)
        if self.header and "Content-Security-Policy" not in response:
            if not request.path.startswith("/django-admin/") and not request.path.startswith(
                "/__debug__/"
            ):
                response["Content-Security-Policy"] = self.header
        return response
