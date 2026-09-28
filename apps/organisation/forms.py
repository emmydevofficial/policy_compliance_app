from django import forms

from apps.accounts.models import Role, User

from .models import Department


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "code", "gm"]
        labels = {"gm": "General Manager"}
        help_texts = {
            "code": "Short code, e.g. HSE, FIN, LEGAL. Used in email addresses and reports."
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = User.objects.active().filter(role=Role.OFFICER)
        if self.instance.pk:
            qs = qs.filter(department=self.instance)
        else:
            qs = qs.none()
            self.fields["gm"].help_text = "Save the department, add its people, then pick the GM."
        self.fields["gm"].queryset = qs
        self.fields["gm"].required = False


class PersonForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "full_name",
            "email",
            "job_title",
            "phone",
            "role",
            "department",
            "is_department_gm",
        ]
        labels = {"is_department_gm": "This person is the department GM"}
        help_texts = {
            "department": "Required for Officers. Leave empty for Admin and Executive users.",
            "is_department_gm": "Copied on the department's notices; can submit on behalf of "
            "its officers.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Department

        self.fields["department"].queryset = Department.objects.active()
        self.fields["department"].required = False

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        clash = User.objects.filter(email=email).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("Someone already has this email address.")
        return email


class PeopleImportForm(forms.Form):
    file = forms.FileField(
        label="CSV file",
        help_text="Columns: full_name, email, job_title, phone, role, "
        "department_code, is_department_gm",
    )

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > 2 * 1024 * 1024:
            raise forms.ValidationError("The CSV is larger than 2 MB.")
        try:
            return f.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise forms.ValidationError("Save the file as UTF-8 CSV and try again.") from exc


class ReassignBeforeDeactivateForm(forms.Form):
    """One select per open request: who takes it over."""

    def __init__(self, *args, requests=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = list(requests)
        for req in self.requests:
            qs = (
                User.objects.active()
                .filter(role=Role.OFFICER, department=req.assigned_department)
                .exclude(pk=req.assigned_officer_id)
            )
            self.fields[f"req_{req.pk}"] = forms.ModelChoiceField(
                queryset=qs, label=f"{req.obligation.obligation_id} – due {req.due_date:%d %b %Y}"
            )

    def mapping(self) -> dict:
        return {req.pk: self.cleaned_data[f"req_{req.pk}"] for req in self.requests}
