from django.contrib import admin

from .models import WebhookDelivery, WebhookEndpoint


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ["agency", "url", "is_active", "consecutive_failures", "created_at"]
    exclude = ["secret"]


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ["created_at", "endpoint", "event", "status", "attempts", "response_status"]
    list_filter = ["status", "event"]
