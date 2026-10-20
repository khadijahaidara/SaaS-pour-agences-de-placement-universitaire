from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse_lazy


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        slug = self.request.GET.get("agence", "")
        if slug:
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
    from django.contrib.auth.forms import PasswordChangeForm
    from django.shortcuts import render

    from .forms import ProfileForm

    user = request.user
    profile_form = ProfileForm(instance=user, prefix="p")
    password_form = PasswordChangeForm(user, prefix="pw")
    for f in password_form.fields.values():
        f.widget.attrs.setdefault("class", "input")
    if request.method == "POST":
        if "save_profile" in request.POST:
            profile_form = ProfileForm(request.POST, instance=user, prefix="p")
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profil mis à jour.")
                return redirect("accounts:profile")
        elif "change_password" in request.POST:
            password_form = PasswordChangeForm(user, request.POST, prefix="pw")
            for f in password_form.fields.values():
                f.widget.attrs.setdefault("class", "input")
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Mot de passe modifié.")
                return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {
        "layout": layout_for(user), "profile_form": profile_form, "password_form": password_form,
    })
