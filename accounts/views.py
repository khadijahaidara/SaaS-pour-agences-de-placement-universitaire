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
