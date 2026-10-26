from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("journal/", views.journal, name="journal"),
    path("journal/export/", views.journal_export, name="journal_export"),
]
