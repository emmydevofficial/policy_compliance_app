from django import forms

from .models import Holiday, NotificationTemplate, ReminderRule
from .rendering import validate_template


class ReminderRuleForm(forms.ModelForm):
    days_before_text = forms.CharField(
        label="Reminders before the deadline (days)", help_text="Comma-separated, e.g. 14, 7, 3, 1"
    )

    class Meta:
        model = ReminderRule
        fields = [
            "send_on_due_date",
            "repeat_every_working_days",
            "stop_after_count",
            "escalate_gm_after_days",
            "escalate_management_after_days",
            "escalate_management_high_risk_only",
            "send_time",
            "working_days_only",
            "email_enabled",
            "sms_enabled",
            "in_app_enabled",
        ]
        widgets = {"send_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}
        labels = {
            "send_on_due_date": "Send a final notice on the deadline",
            "repeat_every_working_days": "After the deadline, repeat every N working days",
            "stop_after_count": "Stop overdue notices after this many (empty = never)",
            "escalate_gm_after_days": "Default: escalate to department GM after (working days)",
            "escalate_management_after_days": "Escalate to Executive Management after "
            "(working days)",
            "escalate_management_high_risk_only": "Escalate to management for High risk only",
            "send_time": "Send time (Lagos)",
            "working_days_only": "Send on working days only",
            "email_enabled": "Email",
            "sms_enabled": "SMS (no gateway integrated yet)",
            "in_app_enabled": "In-app",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["days_before_text"].initial = ", ".join(
            str(d) for d in self.instance.days_before
        )

    def clean_days_before_text(self):
        raw = self.cleaned_data["days_before_text"]
        try:
            days = sorted(
                {int(x) for x in raw.replace(";", ",").split(",") if x.strip()}, reverse=True
            )
        except ValueError as exc:
            raise forms.ValidationError("Use whole numbers separated by commas.") from exc
        if not days or any(d <= 0 for d in days):
            raise forms.ValidationError("Give at least one number of days, above zero.")
        return days

    def clean(self):
        data = super().clean()
        if "days_before_text" in data:
            self.instance.days_before = data["days_before_text"]
        return data


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["date", "name"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class TemplateForm(forms.ModelForm):
    class Meta:
        model = NotificationTemplate
        fields = ["name", "subject_template", "body_template", "is_active"]
        widgets = {"body_template": forms.Textarea(attrs={"rows": 18})}

    def clean_subject_template(self):
        v = self.cleaned_data["subject_template"]
        if problem := validate_template(v):
            raise forms.ValidationError(problem)
        return v

    def clean_body_template(self):
        v = self.cleaned_data["body_template"]
        if problem := validate_template(v):
            raise forms.ValidationError(problem)
        return v
