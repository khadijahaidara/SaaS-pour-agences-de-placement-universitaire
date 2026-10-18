from django.urls import path

from . import views

app_name = "agencies"

urlpatterns = [
    path("agence/", views.agency_settings, name="settings"),
    path("equipe/", views.team, name="team"),
    path("equipe/<int:user_id>/activation/", views.toggle_member, name="toggle_member"),
    path("equipe/<int:user_id>/invitation/", views.member_invitation, name="member_invitation"),
    path("parcours/", views.workflow_list, name="workflows"),
    path("parcours/nouveau/", views.workflow_edit, name="workflow_create"),
    path("parcours/<int:pk>/", views.workflow_edit, name="workflow_edit"),
]
