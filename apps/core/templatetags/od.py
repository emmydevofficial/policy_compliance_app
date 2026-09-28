from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def action_label(value: str) -> str:
    return (value or "").replace("_", " ").capitalize()


@register.filter
def countdown(due) -> str:
    """'5 days left', 'Due today', '3 days overdue'."""
    if not due:
        return ""
    days = (due - timezone.localdate()).days
    if days > 1:
        return f"{days} days left"
    if days == 1:
        return "1 day left"
    if days == 0:
        return "Due today"
    return f"{-days} day{'s' if days < -1 else ''} overdue"


@register.filter
def pct(part, whole) -> int:
    try:
        return round(100 * part / whole) if whole else 0
    except (TypeError, ZeroDivisionError):
        return 0


@register.filter
def items(value: str) -> list[str]:
    """Split a semicolon-separated evidence list."""
    return [p.strip() for p in (value or "").split(";") if p.strip()]
