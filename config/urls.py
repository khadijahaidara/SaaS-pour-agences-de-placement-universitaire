from django.contrib import admin
from django.urls import include, path

from accounts.views import home

admin.site.site_header = "Neuralis Placement — administration plateforme"

urlpatterns = [
    path("", home, name="home"),
    path("compte/", include("accounts.urls")),
    path("agence/", include("dossiers.urls")),
    path("agence/parametres/", include("agencies.urls")),
    path("etudiant/", include("portal.urls")),
    path("plateforme/admin/", admin.site.urls),
]
