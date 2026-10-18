from django.urls import path

from . import views

app_name = "agencies"

urlpatterns = [
    path("equipe/", views.team, name="team"),
    path("equipe/<int:user_id>/activation/", views.toggle_member, name="toggle_member"),
    path("parcours/", views.workflow_list, name="workflows"),
    path("parcours/nouveau/", views.workflow_edit, name="workflow_create"),
    path("parcours/<int:pk>/", views.workflow_edit, name="workflow_edit"),
]
