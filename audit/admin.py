from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "agency", "actor_label", "action", "target_label", "ip"]
    list_filter = ["action"]
    search_fields = ["actor_label", "target_label", "agency__name"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False
