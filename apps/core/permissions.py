"""Role decorators. Every view in the application carries exactly one of these.

Object-level checks (does this request belong to the caller's department?) are separate and
explicit; see the `can_*` helpers on the models and the services that use them.
"""

from collections.abc import Callable, Iterable
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

ADMIN = "ADMIN"
OFFICER = "OFFICER"
EXECUTIVE = "EXECUTIVE"
ALL_ROLES = (ADMIN, OFFICER, EXECUTIVE)

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _role_required(roles: Iterable[str], *, read_only: bool = False) -> Callable:
    roles = tuple(roles)

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user.is_active or user.role not in roles:
                raise PermissionDenied
            if read_only and request.method not in SAFE_METHODS:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        wrapped.permission_roles = roles  # type: ignore[attr-defined]
        return wrapped

    return decorator


def admin_required(view: Callable) -> Callable:
    return _role_required([ADMIN])(view)


def officer_required(view: Callable) -> Callable:
    return _role_required([OFFICER])(view)


def executive_or_above(view: Callable) -> Callable:
    """ADMIN or EXECUTIVE. Executives only ever get safe methods."""
    return _role_required([ADMIN, EXECUTIVE])(view)


def any_role_required(view: Callable) -> Callable:
    """Any signed-in, active user with a role."""
    return _role_required(ALL_ROLES)(view)


def public_view(view: Callable) -> Callable:
    """Explicitly marks a view that needs no sign-in (login, activation, password reset)."""
    view.permission_roles = ("PUBLIC",)  # type: ignore[attr-defined]
    return view
