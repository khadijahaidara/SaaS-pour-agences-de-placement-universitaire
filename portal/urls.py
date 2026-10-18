from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.home, name="home"),
    path("dossier/<int:pk>/", views.dossier, name="dossier"),
    path("dossier/<int:pk>/pieces/<int:doc_id>/deposer/", views.upload, name="upload"),
]
