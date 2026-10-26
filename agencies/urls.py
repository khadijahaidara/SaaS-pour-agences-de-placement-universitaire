from django.urls import path

from . import views

app_name = "agencies"

urlpatterns = [
    path("agence/", views.agency_settings, name="settings"),
    path("recus/", views.receipt_settings, name="receipts"),
    path("adresse-web/", views.web_address, name="web_address"),
    path("prestations/", views.offer_list, name="offers"),
    path("prestations/nouvelle/", views.offer_edit, name="offer_create"),
    path("prestations/<int:pk>/", views.offer_edit, name="offer_edit"),
    path("champs/", views.field_list, name="fields"),
    path("champs/nouveau/", views.field_edit, name="field_create"),
    path("champs/<int:pk>/", views.field_edit, name="field_edit"),
    path("messages/", views.template_list, name="templates"),
    path("messages/nouveau/", views.template_edit, name="template_create"),
    path("messages/<int:pk>/", views.template_edit, name="template_edit"),
    path("api/", views.api_keys, name="api_keys"),
    path("api/<int:pk>/revoquer/", views.api_key_revoke, name="api_key_revoke"),
    path("equipe/", views.team, name="team"),
    path("equipe/<int:user_id>/role/", views.member_role, name="member_role"),
    path("roles/", views.role_list, name="roles"),
    path("roles/nouveau/", views.role_edit, name="role_create"),
    path("roles/<int:pk>/", views.role_edit, name="role_edit"),
    path("roles/<int:pk>/supprimer/", views.role_delete, name="role_delete"),
    path("securite/", views.security_settings, name="security"),
    path("equipe/<int:user_id>/activation/", views.toggle_member, name="toggle_member"),
    path("equipe/<int:user_id>/invitation/", views.member_invitation, name="member_invitation"),
    path("parcours/", views.workflow_list, name="workflows"),
    path("parcours/nouveau/", views.workflow_edit, name="workflow_create"),
    path("parcours/<int:pk>/", views.workflow_edit, name="workflow_edit"),
]
