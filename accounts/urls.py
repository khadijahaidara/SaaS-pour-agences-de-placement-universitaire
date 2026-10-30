from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import TemplateView

from . import security_views, views

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.LoginView.as_view(), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("compte-inactif/", TemplateView.as_view(template_name="accounts/no_space.html"), name="logout_page"),
    path("activation/<uidb64>/<token>/", views.InvitationView.as_view(), name="invitation"),
    path("activation/terminee/", views.InvitationDoneView.as_view(), name="invitation_done"),
    path("mot-de-passe/oublie/", views.PasswordResetView.as_view(), name="password_reset"),
    path("mot-de-passe/envoye/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("profil/", views.profile, name="profile"),
    path("preferences/tableau-de-bord/", views.dashboard_layout, name="dashboard_layout"),
    path("preferences/theme/", views.set_theme, name="set_theme"),
    path("connexion/verification/", security_views.login_2fa, name="login_2fa"),
    path("securite/", security_views.security_page, name="security"),
    path("securite/2fa/demarrer/", security_views.totp_start, name="totp_start"),
    path("securite/2fa/confirmer/", security_views.totp_confirm, name="totp_confirm"),
    path("securite/2fa/desactiver/", security_views.totp_disable, name="totp_disable"),
    path("securite/codes-de-secours/", security_views.recovery_regenerate, name="recovery_regenerate"),
    path("securite/sessions/<int:pk>/deconnecter/", security_views.session_revoke, name="session_revoke"),
    path("securite/sessions/deconnecter-autres/", security_views.sessions_revoke_others, name="sessions_revoke_others"),
]
