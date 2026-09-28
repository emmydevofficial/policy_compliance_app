"""Default wording for the ten notice templates (SPEC 9). All editable in the application."""

DEFAULT_TEMPLATES = {
    "evidence_request": (
        "Evidence request",
        "Evidence required: {{ obligation_id }} – due {{ deadline }}",
        """Dear {{ officer_name }},

The Regulation & Compliance department requests evidence of compliance with {{ obligation_id }} ({{ instrument }}, {{ document_reference }}) for {{ period_name }}.

{{ obligation_text }}

Please provide:
{{ evidence_list }}

The deadline is {{ deadline }} ({{ days_remaining }} day{{ days_remaining|pluralize }} from today). Upload your evidence and state the compliance position here: {{ upload_link }}

Risk level: {{ risk_level }}. Consequence of non-compliance: {{ consequence }}

Regards,
GM, Regulation & Compliance""",
    ),
    "reminder_before": (
        "Reminder before the deadline",
        "Reminder: {{ obligation_id }} evidence due in {{ days_remaining }} day{{ days_remaining|pluralize }}",
        """Dear {{ officer_name }},

This is a reminder that evidence for {{ obligation_id }} ({{ document_reference }}) is due on {{ deadline }}, {{ days_remaining }} day{{ days_remaining|pluralize }} from today.

Please provide:
{{ evidence_list }}

Upload here: {{ upload_link }}

Regards,
Regulation & Compliance""",
    ),
    "final_notice": (
        "Final notice on the deadline",
        "Final notice: {{ obligation_id }} evidence is due today",
        """Dear {{ officer_name }},

Evidence for {{ obligation_id }} ({{ document_reference }}) is due today, {{ deadline }}.

If it is not received today the request will be recorded as overdue and escalated to {{ gm_name }}.

Upload here: {{ upload_link }}

Regards,
Regulation & Compliance""",
    ),
    "overdue_notice": (
        "Overdue notice",
        "Overdue: {{ obligation_id }} evidence is {{ days_overdue }} day{{ days_overdue|pluralize }} late",
        """Dear {{ officer_name }},

Evidence for {{ obligation_id }} ({{ document_reference }}) was due on {{ deadline }} and is now {{ days_overdue }} day{{ days_overdue|pluralize }} overdue.

Consequence of non-compliance: {{ consequence }}

Please upload the evidence, or an action plan, now: {{ upload_link }}

Regards,
Regulation & Compliance""",
    ),
    "escalation_gm": (
        "Escalation to department GM",
        "Escalation: {{ department_name }} – {{ obligation_id }} is {{ days_overdue }} day{{ days_overdue|pluralize }} overdue",
        """Dear {{ gm_name }},

Evidence for {{ obligation_id }} ({{ instrument }}, {{ document_reference }}), assigned to {{ department_name }}, was due on {{ deadline }} and is {{ days_overdue }} day{{ days_overdue|pluralize }} overdue.

{{ obligation_text }}

Risk level: {{ risk_level }}. Consequence of non-compliance: {{ consequence }}

Please ensure the evidence is submitted without further delay: {{ upload_link }}

Regards,
GM, Regulation & Compliance""",
    ),
    "escalation_management": (
        "Escalation to Executive Management",
        "Executive escalation: {{ obligation_id }} ({{ risk_level }} risk) is {{ days_overdue }} day{{ days_overdue|pluralize }} overdue",
        """For the attention of Executive Management,

Evidence for {{ obligation_id }} ({{ instrument }}, {{ document_reference }}), assigned to {{ department_name }}, was due on {{ deadline }} and remains outstanding {{ days_overdue }} day{{ days_overdue|pluralize }} later, despite reminders and escalation to {{ gm_name }}.

{{ obligation_text }}

Consequence of non-compliance: {{ consequence }}

Details: {{ upload_link }}

GM, Regulation & Compliance""",
    ),
    "submission_received": (
        "Submission received",
        "Received: your submission for {{ obligation_id }}",
        """Dear {{ officer_name }},

Thank you. Your submission for {{ obligation_id }} ({{ period_name }}) has been received and is awaiting verification by Regulation & Compliance.

You will be told when it has been verified, or if anything more is needed.

Regards,
Regulation & Compliance""",
    ),
    "submission_returned": (
        "Submission returned",
        "Returned: {{ obligation_id }} needs more information",
        """Dear {{ officer_name }},

Your submission for {{ obligation_id }} ({{ document_reference }}) has been returned for the following reason:

{{ reason }}

Please address this and resubmit by {{ deadline }}: {{ upload_link }}

Regards,
Regulation & Compliance""",
    ),
    "submission_verified": (
        "Submission verified",
        "Verified: {{ obligation_id }} for {{ period_name }}",
        """Dear {{ officer_name }},

Your submission for {{ obligation_id }} ({{ document_reference }}) for {{ period_name }} has been verified. No further action is needed on this request.

Thank you.

Regards,
Regulation & Compliance""",
    ),
    "weekly_digest": (
        "Weekly digest",
        "Obligation Desk summary: {{ department_name }}",
        """Dear {{ officer_name }},

Here is the position for {{ department_name }} in {{ period_name }} as at {{ deadline }}:

{{ digest_lines }}

Open Obligation Desk: {{ upload_link }}

Regards,
Regulation & Compliance""",
    ),
}
