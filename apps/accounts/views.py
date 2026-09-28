from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import SetPasswordForm
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator

from apps.auditlog.services import Action, record
from apps.core import ratelimit
from apps.core.permissions import any_role_required, officer_required, public_view

from . import services
from .forms import ContactDetailsForm, DelegationForm, EmailAuthenticationForm, PreferencesForm
from .models import Invitation, NotificationPreference, Role


@any_role_required
def home(request):
    role = request.user.role
    if role == Role.ADMIN:
        return redirect("dashboard:admin")
    if role == Role.EXECUTIVE:
        return redirect("dashboard:executive")
    return redirect("my:inbox")


@method_decorator(public_view, name="dispatch")
class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def _limited(self) -> bool:
        limit, _ = settings.RATE_LIMIT_LOGIN
        ip = ratelimit.client_ip(self.request) or "unknown"
        email = (self.request.POST.get("username") or "").lower()
        return ratelimit.is_limited("login-ip", ip, limit) or (
            bool(email) and ratelimit.is_limited("login-email", email, limit)
        )

    def post(self, request, *args, **kwargs):
        if self._limited():
            services.sign_in_failed(request.POST.get("username", ""), request, "rate limited")
            form = self.get_form()
            form.errors.clear()
            form.add_error(None, "Too many sign-in attempts. Wait 15 minutes and try again.")
            response = self.render_to_response(self.get_context_data(form=form))
            response.status_code = 429
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        ip = ratelimit.client_ip(self.request) or "unknown"
        ratelimit.reset("login-email", form.get_user().email)
        ratelimit.reset("login-ip", ip)
        services.signed_in(form.get_user(), self.request)
        return response

    def form_invalid(self, form):
        _, window = settings.RATE_LIMIT_LOGIN
        email = (self.request.POST.get("username") or "").lower()
        ratelimit.hit("login-ip", ratelimit.client_ip(self.request) or "unknown", window)
        if email:
            ratelimit.hit("login-email", email, window)
        services.sign_in_failed(email, self.request)
        return super().form_invalid(form)


@method_decorator(any_role_required, name="dispatch")
class LogoutView(auth_views.LogoutView):
    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            record(
                Action.SIGN_OUT,
                actor=request.user,
                obj=request.user,
                request=request,
                detail="Signed out.",
            )
        return super().post(request, *args, **kwargs)


@method_decorator(any_role_required, name="dispatch")
class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:password_change_done")

    def form_valid(self, form):
        response = super().form_valid(form)
        record(
            Action.PASSWORD_CHANGED,
            actor=self.request.user,
            obj=self.request.user,
            request=self.request,
            detail="Password changed.",
        )
        return response


@method_decorator(any_role_required, name="dispatch")
class PasswordChangeDoneView(auth_views.PasswordChangeDoneView):
    template_name = "accounts/password_change_done.html"


@method_decorator(public_view, name="dispatch")
class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "emails/password_reset.txt"
    subject_template_name = "emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def post(self, request, *args, **kwargs):
        limit, window = settings.RATE_LIMIT_PASSWORD_RESET
        ip = ratelimit.client_ip(request) or "unknown"
        if ratelimit.is_limited("reset-ip", ip, limit):
            form = self.get_form()
            form.is_valid()
            form.add_error(None, "Too many reset requests. Try again in an hour.")
            response = self.render_to_response(self.get_context_data(form=form))
            response.status_code = 429
            return response
        ratelimit.hit("reset-ip", ip, window)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        record(
            Action.PASSWORD_RESET_REQUESTED,
            object_type="User",
            request=self.request,
            detail=f"Password reset requested for {form.cleaned_data['email']}.",
        )
        return super().form_valid(form)


@method_decorator(public_view, name="dispatch")
class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


@method_decorator(public_view, name="dispatch")
class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


@method_decorator(public_view, name="dispatch")
class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@public_view
def activate(request, token: str):
    inv = Invitation.find_usable(token)
    if inv is None or not inv.user.is_active:
        return render(request, "accounts/activate_invalid.html", status=410)
    form = SetPasswordForm(inv.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.activate(inv, form.cleaned_data["new_password1"], http_request=request)
        messages.success(request, "Your password is set. Sign in to continue.")
        return redirect("accounts:login")
    return render(request, "accounts/activate.html", {"form": form, "invitee": inv.user})


@officer_required
def my_settings(request):
    user = request.user
    prefs, _ = NotificationPreference.objects.get_or_create(user=user)
    contact = ContactDetailsForm(request.POST or None, instance=user, prefix="c")
    pref_form = PreferencesForm(request.POST or None, instance=prefs, prefix="p")
    delegation = DelegationForm(request.POST or None, instance=user, prefix="d")
    if request.method == "POST":
        if contact.is_valid() and pref_form.is_valid() and delegation.is_valid():
            contact.save(commit=False)
            delegation.save(commit=False)
            services.save_preferences(user, pref_form.save(commit=False), http_request=request)
            messages.success(request, "Your settings are saved.")
            return redirect("my:settings")
    return render(
        request,
        "my/settings.html",
        {
            "contact": contact,
            "prefs": pref_form,
            "delegation": delegation,
        },
    )
