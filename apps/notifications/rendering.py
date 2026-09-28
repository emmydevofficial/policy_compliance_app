"""Rendering notice templates against a fixed, restricted context (SPEC 9).

A dedicated template Engine with no loadable libraries: only the built-in tags and filters.
The context contains plain strings and numbers, never model instances, so a template cannot
reach anything beyond the listed placeholders.
"""

from django.template import Context, Engine, TemplateSyntaxError
from django.template.loader import render_to_string

PLACEHOLDERS = (
    "officer_name",
    "department_name",
    "obligation_id",
    "obligation_text",
    "instrument",
    "document_reference",
    "risk_level",
    "evidence_list",
    "deadline",
    "days_remaining",
    "days_overdue",
    "consequence",
    "upload_link",
    "gm_name",
    "period_name",
    "reason",
)
# Only the weekly digest uses this one: a pre-rendered list of the department's open items.
DIGEST_PLACEHOLDER = "digest_lines"

_engine = Engine(libraries={}, autoescape=False, debug=False)
_FORBIDDEN_TAGS = ("{% load", "{% include", "{% extends", "{% debug", "{% ssi")


def validate_template(source: str) -> str | None:
    lowered = source.replace(" ", "").lower()
    for tag in _FORBIDDEN_TAGS:
        if tag.replace(" ", "") in lowered:
            return f"The tag {tag.strip('{% ')} is not allowed in notice templates."
    try:
        _engine.from_string(source)
    except TemplateSyntaxError as exc:
        return f"Template error: {exc}"
    return None


def render_text(source: str, context: dict) -> str:
    problem = validate_template(source)
    if problem:
        raise TemplateSyntaxError(problem)
    allowed = {k: v for k, v in context.items() if k in PLACEHOLDERS or k == DIGEST_PLACEHOLDER}
    return _engine.from_string(source).render(Context(allowed, autoescape=False)).strip()


def render_notice(template, context: dict) -> tuple[str, str, str]:
    """Return (subject, text body, html body)."""
    subject = " ".join(render_text(template.subject_template, context).split())[:255]
    body = render_text(template.body_template, context)
    html = render_to_string(
        "emails/notice.html",
        {
            "subject": subject,
            "paragraphs": [p for p in body.split("\n\n") if p.strip()],
            "ctx": {k: context.get(k, "") for k in PLACEHOLDERS},
            "has_obligation": bool(context.get("obligation_id")),
        },
    )
    return subject, body, html
