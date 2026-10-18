from django.contrib import admin

from .models import Prospect, ProspectActivity


class ActivityInline(admin.TabularInline):
    model = ProspectActivity
    extra = 0


@admin.register(Prospect)
class ProspectAdmin(admin.ModelAdmin):
    list_display = ("name", "priority", "status", "zone", "owner", "next_follow_up")
    list_filter = ("priority", "status")
    search_fields = ("name", "email", "phone")
    inlines = [ActivityInline]
