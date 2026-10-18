from django.urls import path

from . import views

app_name = "dossiers"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dossiers/", views.dossier_list, name="list"),
    path("dossiers/nouveau/", views.dossier_create, name="create"),
    path("dossiers/<int:pk>/", views.dossier_detail, name="detail"),
    path("dossiers/<int:pk>/modifier/", views.dossier_edit, name="edit"),
    path("dossiers/<int:pk>/etape/suivante/", views.advance_stage, name="advance_stage"),
    path("dossiers/<int:pk>/etape/<int:stage_id>/echeance/", views.stage_due_date, name="stage_due_date"),
    path("dossiers/<int:pk>/statut/", views.set_status, name="set_status"),
    path("dossiers/<int:pk>/conseiller/", views.assign, name="assign"),
    path("dossiers/<int:pk>/pieces/demander/", views.request_document, name="request_document"),
    path("dossiers/<int:pk>/pieces/<int:doc_id>/verifier/", views.review_document, name="review_document"),
    path("dossiers/<int:pk>/pieces/<int:doc_id>/deposer/", views.upload_document, name="upload_document"),
    path("dossiers/<int:pk>/frais/", views.add_fee, name="add_fee"),
    path("dossiers/<int:pk>/paiements/", views.record_payment, name="record_payment"),
    path("dossiers/<int:pk>/paiements/<int:payment_id>/annuler/", views.cancel_payment, name="cancel_payment"),
    path("fichiers/<int:file_id>/", views.document_download, name="document_download"),
    path("recus/<int:payment_id>/", views.payment_receipt, name="receipt"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/<int:notif_id>/ouvrir/", views.notification_open, name="notification_open"),
    path("notifications/tout-lu/", views.notifications_mark_all, name="notifications_mark_all"),
]
