from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import NotificationPreference, Role, User


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )

    def clean_username(self):
        return (self.cleaned_data.get("username") or "").lower()


class ContactDetailsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "job_title", "phone"]


class PreferencesForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = [
            "new_request",
            "deadline_reminders",
            "sms_when_overdue",
            "outcome_notices",
            "weekly_digest",
        ]
        labels = {
            "new_request": "New evidence requests",
            "deadline_reminders": "Deadline reminders for Medium and Low risk obligations",
            "sms_when_overdue": "SMS when a request is overdue (not yet available)",
            "outcome_notices": "Outcome notices (received, returned, verified)",
            "weekly_digest": "Friday weekly digest",
        }


class DelegationForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["delegate_to", "delegate_from", "delegate_until"]
        widgets = {
            "delegate_from": forms.DateInput(attrs={"type": "date"}),
            "delegate_until": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "delegate_to": "Who covers for you",
            "delegate_from": "From",
            "delegate_until": "Until",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        me = self.instance
        self.fields["delegate_to"].queryset = (
            User.objects.active()
            .filter(role=Role.OFFICER, department_id=me.department_id)
            .exclude(pk=me.pk)
        )
        self.fields["delegate_to"].required = False
