from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse_lazy


class TenantAuthenticationForm(AuthenticationForm):
    """Sur l'adresse d'une agence, seuls ses membres (et l'équipe NEURALIS) peuvent se connecter."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        tenant = getattr(self.request, "tenant", None)
        if tenant is not None and user.role != user.Role.PLATFORM_ADMIN and user.agency_id != tenant.id:
            raise ValidationError(f"Ce compte n'appartient pas à {tenant.name}.", code="wrong_agency")


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    authentication_form = TenantAuthenticationForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["login_agency"] = getattr(self.request, "tenant", None)
        slug = self.request.GET.get("agence", "")
        if slug and ctx["login_agency"] is None:
            from agencies.models import Agency

            ctx["login_agency"] = Agency.objects.filter(slug=slug, is_active=True).first()
        return ctx


class InvitationView(auth_views.PasswordResetConfirmView):
    """Lien d'activation : l'étudiant ou le conseiller choisit son mot de passe."""

    template_name = "accounts/invitation.html"
    success_url = reverse_lazy("accounts:invitation_done")
    post_reset_login = True
    post_reset_login_backend = "django.contrib.auth.backends.ModelBackend"


class InvitationDoneView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/invitation_done.html"


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


@login_required
def home(request):
    """Aiguille chaque utilisateur vers son espace."""
    user = request.user
    if user.is_student:
        return redirect("portal:home")
    if user.is_agency_staff:
        return redirect("dossiers:dashboard")
    if user.role == user.Role.PLATFORM_ADMIN:
        return redirect("console:dashboard")
    return redirect("accounts:logout_page")


def layout_for(user) -> str:
    """Gabarit de mise en page adapté au rôle (portail pour les étudiants)."""
    return "layouts/portal.html" if user.is_student else "layouts/app.html"


@login_required
def profile(request):
    from django.contrib import messages
    from django.contrib.auth import update_session_auth_hash
    from django.shortcuts import render

    from .forms import NotificationPrefsForm, ProfileForm, StyledPasswordChangeForm

    user = request.user
    profile_form = ProfileForm(instance=user, prefix="p")
    prefs_form = NotificationPrefsForm(instance=user, prefix="n")
    password_form = StyledPasswordChangeForm(user, prefix="pw")
    if request.method == "POST":
        if "save_profile" in request.POST:
            profile_form = ProfileForm(request.POST, instance=user, prefix="p")
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Informations personnelles enregistrées.")
                return redirect("accounts:profile")
        elif "save_prefs" in request.POST:
            prefs_form = NotificationPrefsForm(request.POST, instance=user, prefix="n")
            if prefs_form.is_valid():
                prefs_form.save()
                messages.success(request, "Préférences de notification enregistrées.")
                return redirect("accounts:profile")
        elif "change_password" in request.POST:
            password_form = StyledPasswordChangeForm(user, request.POST, prefix="pw")
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Mot de passe modifié. Vos autres sessions restent connectées jusqu'à leur expiration.")
                return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {
        "layout": layout_for(user), "profile_form": profile_form, "prefs_form": prefs_form,
        "password_form": password_form,
    })
