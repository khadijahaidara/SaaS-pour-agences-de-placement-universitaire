from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("webhooks/", views.webhooks, name="webhooks"),
    path("webhooks/nouveau/", views.webhook_edit, name="webhook_create"),
    path("webhooks/<int:pk>/", views.webhook_detail, name="webhook_detail"),
    path("webhooks/<int:pk>/modifier/", views.webhook_edit, name="webhook_edit"),
    path("webhooks/<int:pk>/test/", views.webhook_test, name="webhook_test"),
    path("webhooks/<int:pk>/activation/", views.webhook_toggle, name="webhook_toggle"),
    path("webhooks/<int:pk>/secret/", views.webhook_rotate, name="webhook_rotate"),
    path("webhooks/<int:pk>/supprimer/", views.webhook_delete, name="webhook_delete"),
    path("webhooks/<int:pk>/livraisons/<int:delivery_id>/renvoyer/", views.delivery_resend, name="delivery_resend"),
]
