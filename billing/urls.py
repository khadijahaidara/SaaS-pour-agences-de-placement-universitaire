from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("changer/", views.request_change, name="request_change"),
    path("factures/<int:pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
]
