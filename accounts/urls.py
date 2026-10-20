from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import TemplateView

from . import views

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
]
