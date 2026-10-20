from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from accounts.views import home
from agencies.views import agency_logo, signup

admin.site.site_header = "NEURALIS Mobility — administration technique"

urlpatterns = [
    path("", home, name="home"),
    path("inscription/", signup, name="signup"),
    path("logo/<slug:slug>/", agency_logo, name="agency_logo"),
    path("conditions/", TemplateView.as_view(template_name="legal/terms.html"), name="terms"),
    path("confidentialite/", TemplateView.as_view(template_name="legal/privacy.html"), name="privacy"),
    path("compte/", include("accounts.urls")),
    path("agence/", include("dossiers.urls")),
    path("agence/parametres/", include("agencies.urls")),
    path("etudiant/", include("portal.urls")),
    path("console/", include("console.urls")),
    path("plateforme/admin/", admin.site.urls),
]
