from datetime import date

from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts.models import User
from apps.core.permissions import admin_required

from .models import AuditEvent


def _date(v: str) -> date | None:
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


@admin_required
def audit(request):
    qs = AuditEvent.objects.select_related("actor")
    g = request.GET
    if g.get("actor") == "system":
        qs = qs.filter(actor__isnull=True)
    elif g.get("actor", "").isdigit():
        qs = qs.filter(actor_id=int(g["actor"]))
    if g.get("action"):
        qs = qs.filter(action=g["action"])
    if g.get("obligation"):
        qs = qs.filter(obligation_ref__iexact=g["obligation"].strip())
    if d := _date(g.get("from")):
        qs = qs.filter(occurred_at__date__gte=d)
    if d := _date(g.get("to")):
        qs = qs.filter(occurred_at__date__lte=d)
    page = Paginator(qs, 100).get_page(g.get("page"))
    query = g.copy()
    query.pop("page", None)
    return render(
        request,
        "admin_area/audit.html",
        {
            "page": page,
            "params": g,
            "query": query.urlencode(),
            "actors": User.objects.order_by("full_name"),
            "actions": AuditEvent.objects.order_by("action")
            .values_list("action", flat=True)
            .distinct(),
        },
    )
