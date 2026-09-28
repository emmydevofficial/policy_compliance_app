"""SPEC 2 and 14: every role against every view. The single most important test here."""

from datetime import date

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.core.tests.factories import DepartmentFactory, UserFactory
from apps.core.tests.helpers import good_submission
from apps.notifications.models import Holiday, NotificationTemplate
from apps.workflow import services as wf
from apps.workflow.files import SUBMISSION_TYPES, validate_upload

ADMIN, OFFICER, EXEC, ANON = "admin", "officer", "executive", "anonymous"
ROLES = [ADMIN, OFFICER, EXEC, ANON]


@pytest.fixture
def world(admin, officer_a, gm_a, executive, req_a, pdf_upload):
    wf.add_request_attachment(req_a, pdf_upload("circular.pdf"), admin)
    sub = wf.submit(
        req_a, officer_a, good_submission(), [validate_upload(pdf_upload(), SUBMISSION_TYPES)]
    )
    spare_dept = DepartmentFactory(name="Spare", code="SPARE")
    person = UserFactory(email="spare@example.org", department=spare_dept)
    holiday = Holiday.objects.create(date=date(2031, 1, 1), name="Test holiday")
    return {
        "req": req_a,
        "sub": sub,
        "ob": req_a.obligation,
        "ra": req_a.attachments.first(),
        "sa": sub.attachments.first(),
        "dept": spare_dept,
        "person": person,
        "holiday": holiday,
        "period": req_a.period,
        "tpl": NotificationTemplate.objects.get(key="evidence_request"),
        "users": {ADMIN: admin, OFFICER: officer_a, EXEC: executive},
    }


def _args(world, spec):
    return [world[a] if isinstance(a, str) else a for a in spec]


def _pk(world, key):
    obj = world[key]
    return obj.obligation_id if key == "ob" else obj.pk


# (url name, args from world, roles allowed to GET it)
GET_ROUTES = [
    ("home", [], {ADMIN, OFFICER, EXEC}),
    ("obligations:list", [], {ADMIN, OFFICER, EXEC}),
    ("obligations:detail", ["ob"], {ADMIN, OFFICER, EXEC}),
    ("requests:list", [], {ADMIN}),
    ("requests:create", [], {ADMIN}),
    ("requests:picker", [], {ADMIN}),
    ("requests:officers", [], {ADMIN}),
    ("requests:verify_queue", [], {ADMIN}),
    ("requests:overdue", [], {ADMIN}),
    ("requests:detail", ["req"], {ADMIN}),
    ("requests:attachment_download", ["ra"], {ADMIN, OFFICER, EXEC}),
    ("requests:evidence_download", ["sa"], {ADMIN, OFFICER, EXEC}),
    ("my:inbox", [], {OFFICER}),
    ("my:submit", ["req"], {OFFICER}),
    ("my:history", [], {OFFICER}),
    ("my:settings", [], {OFFICER}),
    ("dashboard:admin", [], {ADMIN}),
    ("dashboard:executive", [], {ADMIN, EXEC}),
    ("reports:index", [], {ADMIN, EXEC}),
    ("reports:preview", [], {ADMIN, EXEC}),
    ("reports:register_xlsx", [], {ADMIN, EXEC}),
    ("reports:tracker_xlsx", [], {ADMIN, EXEC}),
    ("reports:report_pdf", [], {ADMIN, EXEC}),
    ("reports:pack_zip", [], {ADMIN, EXEC}),
    ("admin_area:departments", [], {ADMIN}),
    ("admin_area:department_create", [], {ADMIN}),
    ("admin_area:department_edit", ["dept"], {ADMIN}),
    ("admin_area:people", [], {ADMIN}),
    ("admin_area:person_create", [], {ADMIN}),
    ("admin_area:person_edit", ["person"], {ADMIN}),
    ("admin_area:person_deactivate", ["person"], {ADMIN}),
    ("admin_area:people_import", [], {ADMIN}),
    ("admin_area:reminders", [], {ADMIN}),
    ("admin_area:templates", [], {ADMIN}),
    ("admin_area:template_edit", ["tpl"], {ADMIN}),
    ("admin_area:periods", [], {ADMIN}),
    ("admin_area:audit", [], {ADMIN}),
    ("accounts:password_change", [], {ADMIN, OFFICER, EXEC}),
    ("accounts:password_change_done", [], {ADMIN, OFFICER, EXEC}),
]

# Writes. Only the listed roles may POST; everyone else gets 403 (anonymous: sign-in).
POST_ROUTES = [
    ("requests:preview", [], {ADMIN}),
    ("requests:issue", ["req"], {ADMIN}),
    ("requests:deadline", ["req"], {ADMIN}),
    ("requests:reassign", ["req"], {ADMIN}),
    ("requests:close_na", ["req"], {ADMIN}),
    ("requests:attach", ["req"], {ADMIN}),
    ("requests:verify", ["sub"], {ADMIN}),
    ("requests:create", [], {ADMIN}),
    ("my:submit", ["req"], {OFFICER}),
    ("my:settings", [], {OFFICER}),
    ("admin_area:department_create", [], {ADMIN}),
    ("admin_area:department_edit", ["dept"], {ADMIN}),
    ("admin_area:department_deactivate", ["dept"], {ADMIN}),
    ("admin_area:department_reactivate", ["dept"], {ADMIN}),
    ("admin_area:person_create", [], {ADMIN}),
    ("admin_area:person_edit", ["person"], {ADMIN}),
    ("admin_area:person_deactivate", ["person"], {ADMIN}),
    ("admin_area:person_reactivate", ["person"], {ADMIN}),
    ("admin_area:person_invite", ["person"], {ADMIN}),
    ("admin_area:people_import", [], {ADMIN}),
    ("admin_area:reminders", [], {ADMIN}),
    ("admin_area:holiday_add", [], {ADMIN}),
    ("admin_area:holiday_remove", ["holiday"], {ADMIN}),
    ("admin_area:template_edit", ["tpl"], {ADMIN}),
    ("admin_area:template_preview", ["tpl"], {ADMIN}),
    ("admin_area:periods", [], {ADMIN}),
    ("admin_area:period_toggle", ["period"], {ADMIN}),
]


def _url(world, name, spec):
    return reverse(name, args=[_pk(world, a) for a in spec])


def _client(client, world, role):
    if role != ANON:
        client.force_login(world["users"][role])
    return client


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("name", "spec", "allowed"), GET_ROUTES, ids=[r[0] for r in GET_ROUTES])
def test_get_matrix(client, world, name, spec, allowed, role):
    c = _client(client, world, role)
    r = c.get(_url(world, name, spec))
    if role == ANON:
        assert r.status_code == 302 and "/accounts/sign-in/" in r["Location"]
    elif role in allowed:
        assert r.status_code in (200, 302), f"{role} should reach {name}"
        if r.status_code == 302:
            assert "/accounts/sign-in/" not in r["Location"]
    else:
        assert r.status_code == 403, f"{role} must be refused {name}"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("name", "spec", "allowed"), POST_ROUTES, ids=[r[0] for r in POST_ROUTES])
def test_post_matrix(client, world, name, spec, allowed, role):
    c = _client(client, world, role)
    r = c.post(_url(world, name, spec), {})
    if role == ANON:
        assert r.status_code == 302 and "/accounts/sign-in/" in r["Location"]
    elif role in allowed:
        assert r.status_code in (200, 302)
    else:
        assert r.status_code == 403


def _all_url_names():
    names = []

    def walk(patterns, ns=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                inner = f"{ns}{p.namespace}:" if p.namespace else ns
                if p.namespace in ("admin", "djdt"):
                    continue
                walk(p.url_patterns, inner)
            elif isinstance(p, URLPattern) and p.name:
                names.append((f"{ns}{p.name}", p))

    walk(get_resolver().url_patterns)
    return names


def test_every_application_url_is_in_the_matrix():
    covered = {n for n, _, _ in GET_ROUTES} | {n for n, _, _ in POST_ROUTES}
    public = {
        "accounts:login",
        "accounts:logout",
        "accounts:password_reset",
        "accounts:password_reset_done",
        "accounts:password_reset_confirm",
        "accounts:password_reset_complete",
        "accounts:activate",
    }
    missing = [n for n, _ in _all_url_names() if n not in covered | public]
    assert not missing, f"Add these to the permission matrix: {missing}"


def test_every_view_carries_a_permission_decorator():
    """A view with no permission decorator is a bug, even for a static page."""
    for name, pattern in _all_url_names():
        view = pattern.callback
        if hasattr(view, "view_class"):  # class-based: decorated with method_decorator
            view = view.view_class.dispatch
        marked = getattr(view, "permission_roles", None)
        assert marked, f"{name} has no permission decorator"


@pytest.mark.parametrize(
    ("name", "spec", "allowed"),
    GET_ROUTES + POST_ROUTES,
    ids=[r[0] for r in GET_ROUTES + POST_ROUTES],
)
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_executive_gets_403_on_every_write(client, world, name, spec, allowed, method):
    """SPEC 2 rule 3, including views that only ever expect GET."""
    if name in ("accounts:password_change", "accounts:password_change_done"):
        pytest.skip("An executive may change their own password.")
    client.force_login(world["users"][EXEC])
    r = getattr(client, method)(_url(world, name, spec))
    assert r.status_code == 403
