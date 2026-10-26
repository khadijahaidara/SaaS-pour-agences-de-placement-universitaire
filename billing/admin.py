from django.contrib import admin

from .models import Invoice, Plan, PlanChangeRequest, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "price_monthly", "price_yearly", "max_active_dossiers", "max_staff", "is_public"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["agency", "plan", "cycle", "updated_at"]
    list_filter = ["plan", "cycle"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["number", "agency", "plan", "amount", "status", "issued_on", "paid_on"]
    list_filter = ["status", "plan"]
    search_fields = ["number", "agency__name"]


admin.site.register(PlanChangeRequest)
