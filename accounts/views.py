from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse_lazy


class TenantAuthenticationForm(AuthenticationForm):
    """Sur l'adresse d'une agence, seuls ses membres (et l'équipe NEURALIS) peuvent se connecter.

    Protège aussi contre les essais de mots de passe : après LOGIN_MAX_FAILURES échecs
    pour un même courriel (ou 4× plus pour une même adresse IP), les connexions sont
    refusées pendant LOGIN_LOCKOUT_MINUTES.
    """

    def clean(self):
        from . import security

        email = (self.data.get("username") or "").strip().lower()
        if security.is_locked(self.request, email):
            raise ValidationError(
                "Trop de tentatives de connexion. Pour votre sécurité, réessayez dans quelques minutes "
                "ou réinitialisez votre mot de passe.", code="locked")
        try:
            cleaned = super().clean()
        except ValidationError:
            security.register_failure(self.request, email)
            raise
        security.clear_failures(self.request, email)
        return cleaned

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        tenant = getattr(self.request, "tenant", None)
        if tenant is not None and user.role != user.Role.PLATFORM_ADMIN and user.agency_id != tenant.id:
            raise ValidationError(f"Ce compte n'appartient pas à {tenant.name}.", code="wrong_agency")


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    authentication_form = TenantAuthenticationForm

    def form_valid(self, form):
        from . import security

        user = form.get_user()
        if user.has_2fa:
            security.start_2fa(self.request, user, self.get_success_url())
            return redirect("accounts:login_2fa")
        return super().form_valid(form)

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

    from .forms import DisplayPrefsForm, NotificationPrefsForm, ProfileForm, StyledPasswordChangeForm

    user = request.user
    profile_form = ProfileForm(instance=user, prefix="p")
    prefs_form = NotificationPrefsForm(instance=user, prefix="n")
    password_form = StyledPasswordChangeForm(user, prefix="pw")
    display_form = DisplayPrefsForm(instance=user, prefix="d")
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
        elif "save_display" in request.POST:
            display_form = DisplayPrefsForm(request.POST, instance=user, prefix="d")
            if display_form.is_valid():
                display_form.save()
                messages.success(request, "Affichage enregistré.")
                return redirect("accounts:profile")
        elif "change_password" in request.POST:
            password_form = StyledPasswordChangeForm(user, request.POST, prefix="pw")
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                from audit.services import record

                from .models import UserSession

                for other in UserSession.objects.filter(user=user).exclude(session_key=request.session.session_key):
                    other.revoke()
                record("auth.password_changed", agency=user.agency, actor=user, target=user)
                messages.success(request, "Mot de passe modifié. Vos autres appareils ont été déconnectés.")
                return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {
        "layout": layout_for(user), "profile_form": profile_form, "prefs_form": prefs_form,
        "password_form": password_form, "display_form": display_form,
    })


@login_required
def dashboard_layout(request):
    from django.contrib import messages

    from dossiers.widgets import clean_layout

    if request.method != "POST" or not request.user.is_agency_staff:
        return redirect("home")
    user = request.user
    user.dashboard_layout = [] if request.POST.get("reset") else clean_layout(user, request.POST.getlist("widgets"))
    if not request.POST.get("reset") and not user.dashboard_layout:
        user.dashboard_layout = ["stats"]
    user.save(update_fields=["dashboard_layout"])
    messages.success(request, "Tableau de bord mis à jour.")
    return redirect("dossiers:dashboard")


@login_required
def set_theme(request):
    """Bascule rapide clair / sombre depuis le menu du compte."""
    from django.utils.http import url_has_allowed_host_and_scheme

    if request.method == "POST" and request.POST.get("theme") in request.user.Theme.values:
        request.user.ui_theme = request.POST["theme"]
        request.user.save(update_fields=["ui_theme"])
    nxt = request.POST.get("next") or "/"
    return redirect(nxt if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) else "/")
