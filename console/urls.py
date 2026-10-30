from django.urls import path

from . import views

app_name = "console"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("prospects/", views.prospect_list, name="prospects"),
    path("prospects/nouveau/", views.prospect_edit, name="prospect_create"),
    path("prospects/importer/", views.prospect_import, name="prospect_import"),
    path("prospects/<int:pk>/", views.prospect_detail, name="prospect_detail"),
    path("prospects/<int:pk>/modifier/", views.prospect_edit, name="prospect_edit"),
    path("prospects/<int:pk>/etape/", views.prospect_status, name="prospect_status"),
    path("prospects/<int:pk>/activite/", views.prospect_activity, name="prospect_activity"),
    path("prospects/<int:pk>/convertir/", views.prospect_convert, name="prospect_convert"),
    path("agences/", views.agency_list, name="agencies"),
    path("agences/<int:pk>/formule/", views.agency_plan, name="agency_plan"),
    path("agences/<int:pk>/offre/", views.agency_tier, name="agency_tier"),
    path("agences/<int:pk>/valider/", views.agency_approve, name="agency_approve"),
    path("agences/<int:pk>/refuser/", views.agency_reject, name="agency_reject"),
    path("facturation/", views.billing, name="billing"),
    path("facturation/factures/", views.invoice_create, name="invoice_create"),
    path("facturation/factures/<int:pk>/payee/", views.invoice_paid, name="invoice_paid"),
    path("facturation/factures/<int:pk>/annuler/", views.invoice_void, name="invoice_void"),
    path("facturation/factures/<int:pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
]
