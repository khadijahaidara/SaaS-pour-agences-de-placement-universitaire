from django.contrib import admin
from django.urls import include, path

from accounts.views import home
from agencies.views import agency_logo, signup

admin.site.site_header = "NEURALIS Mobility — administration technique"

urlpatterns = [
    path("", home, name="home"),
    path("inscription/", signup, name="signup"),
    path("logo/<slug:slug>/", agency_logo, name="agency_logo"),
    path("compte/", include("accounts.urls")),
    path("agence/", include("dossiers.urls")),
    path("agence/parametres/", include("agencies.urls")),
    path("etudiant/", include("portal.urls")),
    path("console/", include("console.urls")),
    path("plateforme/admin/", admin.site.urls),
]
