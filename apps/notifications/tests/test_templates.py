import pytest
from django.template import TemplateSyntaxError

from apps.notifications.models import NotificationOutbox, NotificationTemplate
from apps.notifications.rendering import render_notice, render_text, validate_template


def test_placeholders_render():
    assert render_text("Hi {{ officer_name }}", {"officer_name": "Ada"}) == "Hi Ada"


def test_only_listed_placeholders_reach_the_template():
    assert render_text("[{{ secret }}]", {"secret": "x", "officer_name": "Ada"}) == "[]"


@pytest.mark.parametrize(
    "src", ["{% load static %}", "{% include 'base.html' %}", "{% debug %}", "{%   load   i18n %}"]
)
def test_dangerous_tags_are_refused(src):
    assert validate_template(src)
    with pytest.raises(TemplateSyntaxError):
        render_text(src, {})


def test_html_body_uses_tables_and_inline_styles():
    tpl = NotificationTemplate.objects.get(key="evidence_request")
    _, _, html = render_notice(
        tpl,
        {
            "obligation_id": "LIC-001",
            "deadline": "Fri 1 Jan",
            "upload_link": "https://x",
            "consequence": "Fines",
        },
    )
    assert "<table" in html and 'style="' in html and "<style" not in html
    assert "Consequence of breach: Fines" in html


def test_editing_a_template_does_not_change_what_was_sent(req_a):
    from apps.notifications.services import queue_event_notice

    row = queue_event_notice("REQUEST", req_a, send_now=False)
    before = row.subject
    tpl = NotificationTemplate.objects.get(key="evidence_request")
    tpl.subject_template = "CHANGED {{ obligation_id }}"
    tpl.save()
    assert NotificationOutbox.objects.get(pk=row.pk).subject == before


def test_template_edit_screen_rejects_forbidden_tags(client, admin):
    tpl = NotificationTemplate.objects.get(key="reminder_before")
    client.force_login(admin)
    r = client.post(
        f"/manage/templates/{tpl.pk}/",
        {
            "name": tpl.name,
            "subject_template": "x",
            "body_template": "{% load static %}",
            "is_active": "on",
        },
    )
    assert r.status_code == 200 and b"not allowed" in r.content
