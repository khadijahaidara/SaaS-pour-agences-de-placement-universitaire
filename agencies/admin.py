from django.contrib import admin

from .models import Agency


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "country", "is_active", "created_at")
    prepopulated_fields = {"slug": ("name",)}
