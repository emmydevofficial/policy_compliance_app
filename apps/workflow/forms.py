from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.obligations.models import Obligation, RegulatoryInstrument, RiskLevel
from apps.organisation.models import Department

from .files import REQUEST_TYPES, SUBMISSION_TYPES, accepted_labels, validate_upload
from .models import EvidenceAvailable, Submission

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Several files in one input. Each is validated by content (SPEC 7); cleaned_data holds
    a list of CleanFile."""

    def __init__(self, *args, allowed=REQUEST_TYPES, **kwargs):
        self.allowed = allowed
        kwargs.setdefault(
            "widget",
            MultipleFileInput(
                attrs={
                    "accept": ",".join(
                        sorted(
                            {".pdf", ".docx", ".xlsx"}
                            | ({".jpg", ".jpeg", ".png"} if allowed == SUBMISSION_TYPES else set())
                        )
                    )
                }
            ),
        )
        kwargs.setdefault("required", False)
        kwargs.setdefault(
            "help_text", f"Accepted: {accepted_labels(allowed)}. Up to the size limit per file."
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        items = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        items = [d for d in items if d]
        if self.required and not items:
            raise ValidationError(self.error_messages["required"], code="required")
        cleaned, errors = [], []
        for item in items:
            try:
                cleaned.append(validate_upload(item, self.allowed))
            except ValidationError as exc:
                errors.extend(exc.messages)
        if errors:
            raise ValidationError(errors)
        return cleaned


# --- admin: creating requests -----------------------------------------------------------
class RequestCreateForm(forms.Form):
    # Step 1
    obligations = forms.ModelMultipleChoiceField(
        queryset=Obligation.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Choose at least one obligation."},
    )
    # Step 2
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        empty_label="Each obligation's primary department",
        help_text="Leave as is to send each obligation to its own primary department.",
    )
    officer = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label="Whole department",
        help_text="A named officer. Only possible when every request goes to one department.",
    )
    # Step 3
    evidence_required = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        help_text="Leave empty to copy each obligation's own list. Separate items with ;",
    )
    message = forms.CharField(
        label="Covering message", widget=forms.Textarea(attrs={"rows": 4}), required=False
    )
    files = MultipleFileField(
        label="Attach documents (circular, directive, return form)", allowed=REQUEST_TYPES
    )
    # Step 4
    due_date = forms.DateField(label="Deadline", widget=DATE)
    escalate_gm_after_days = forms.IntegerField(
        label="Escalate to the department GM after (working days past the deadline)",
        min_value=1,
        max_value=60,
        initial=5,
    )
    issue_now = forms.TypedChoiceField(
        label="When",
        choices=[("1", "Issue now and notify"), ("0", "Save as draft")],
        coerce=lambda v: v == "1",
        initial="1",
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, available=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["obligations"].queryset = (
            available if available is not None else (Obligation.objects.active())
        )
        self.fields["department"].queryset = Department.objects.active()
        self.fields["officer"].queryset = (
            User.objects.active()
            .filter(role=Role.OFFICER)
            .select_related("department")
            .order_by("department__name", "full_name")
        )

    def clean_due_date(self):
        d = self.cleaned_data["due_date"]
        if d < timezone.localdate():
            raise ValidationError("The deadline is in the past.")
        return d

    def clean(self):
        data = super().clean()
        officer, dept, obs = data.get("officer"), data.get("department"), data.get("obligations")
        if officer and obs:
            targets = {dept.pk} if dept else {o.primary_department_id for o in obs}
            if targets != {officer.department_id}:
                self.add_error(
                    "officer",
                    f"{officer.full_name} is in "
                    f"{officer.department.name}, which is not where "
                    "these requests are going.",
                )
        return data


class ObligationPickerForm(forms.Form):
    """Select obligations by department, instrument or risk (step 1)."""

    pick_department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        empty_label="Any department",
        label="Department",
    )
    pick_instrument = forms.ModelChoiceField(
        queryset=RegulatoryInstrument.objects.none(),
        required=False,
        empty_label="Any instrument",
        label="Instrument",
    )
    pick_risk = forms.ChoiceField(
        choices=[("", "Any risk"), *RiskLevel.choices], required=False, label="Risk"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pick_department"].queryset = Department.objects.active()
        self.fields["pick_instrument"].queryset = RegulatoryInstrument.objects.filter(
            is_active=True
        )

    def matches(self, qs):
        if not self.is_valid():
            return qs.none()
        d = self.cleaned_data
        if not (d.get("pick_department") or d.get("pick_instrument") or d.get("pick_risk")):
            return qs.none()
        if d.get("pick_department"):
            qs = qs.filter(primary_department=d["pick_department"])
        if d.get("pick_instrument"):
            qs = qs.filter(instrument=d["pick_instrument"])
        if d.get("pick_risk"):
            qs = qs.filter(risk_level=d["pick_risk"])
        return qs


# --- admin: changing a request ----------------------------------------------------------
class DeadlineForm(forms.Form):
    due_date = forms.DateField(label="New deadline", widget=DATE)
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), help_text="Required. Recorded in the audit log."
    )


class ReassignForm(forms.Form):
    department = forms.ModelChoiceField(queryset=Department.objects.none())
    officer = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="Whole department"
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), help_text="Required. Recorded in the audit log."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.active()
        self.fields["officer"].queryset = User.objects.active().filter(role=Role.OFFICER)

    def clean(self):
        data = super().clean()
        o, d = data.get("officer"), data.get("department")
        if o and d and o.department_id != d.pk:
            self.add_error("officer", f"{o.full_name} is not in {d.name}.")
        return data


class CloseNAForm(forms.Form):
    justification = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Required. Why this obligation does not apply.",
    )


class RequestAttachmentForm(forms.Form):
    files = MultipleFileField(label="Documents", allowed=REQUEST_TYPES, required=True)
    description = forms.CharField(max_length=255, required=False)


class VerificationForm(forms.Form):
    decision = forms.ChoiceField(choices=[("verify", "Verify"), ("return", "Return")])
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        help_text="Required when returning: tell the officer what is missing.",
    )

    def clean(self):
        data = super().clean()
        if data.get("decision") == "return" and not (data.get("comment") or "").strip():
            self.add_error("comment", "Say why the submission is returned.")
        return data


# --- officer: submitting ----------------------------------------------------------------
class SubmissionForm(forms.ModelForm):
    files = MultipleFileField(label="Evidence files", allowed=SUBMISSION_TYPES)

    class Meta:
        model = Submission
        fields = [
            "compliance_status",
            "evidence_available",
            "evidence_description",
            "date_of_last_review",
            "next_review_due",
            "action_required",
            "action_owner",
            "target_resolution_date",
            "remarks",
        ]
        widgets = {
            "date_of_last_review": DATE,
            "next_review_due": DATE,
            "target_resolution_date": DATE,
            "evidence_description": forms.Textarea(attrs={"rows": 3}),
            "action_required": forms.Textarea(attrs={"rows": 3}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"compliance_status": "Compliance position"}
        help_texts = {
            "target_resolution_date": "No more than 30 days from today.",
            "remarks": "Required for Not applicable: give the justification.",
        }

    def clean(self):
        data = super().clean()  # runs Submission.clean(): SPEC 4 rules 1 and 2
        if (
            data.get("evidence_available")
            and data["evidence_available"] != EvidenceAvailable.NO
            and not data.get("files")
            and "files" not in self.errors
        ):
            self.add_error(
                "files",
                "Attach at least one file, or set Evidence available to No and explain why.",
            )
        return data

    def submission_data(self) -> dict:
        return {f: self.cleaned_data.get(f) for f in self.Meta.fields}
