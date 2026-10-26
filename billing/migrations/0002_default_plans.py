from django.db import migrations

PLANS = [
    {"code": "starter", "name": "Starter", "sort_order": 1, "tagline": "Pour démarrer et digitaliser le suivi.",
     "price_monthly": 25000, "price_yearly": 250000, "max_active_dossiers": 50, "max_staff": 3, "storage_mb": 2048,
     "features": []},
    {"code": "pro", "name": "Pro", "sort_order": 2, "tagline": "Pour les agences en croissance, multi-destinations.",
     "price_monthly": 60000, "price_yearly": 600000, "max_active_dossiers": 300, "max_staff": 10, "storage_mb": 20480,
     "features": ["api", "webhooks", "custom_roles", "audit_log", "enforce_2fa"]},
    {"code": "business", "name": "Business", "sort_order": 3, "tagline": "Pour les réseaux d'agences et les grands volumes.",
     "price_monthly": 150000, "price_yearly": 1500000, "max_active_dossiers": None, "max_staff": None,
     "storage_mb": 102400,
     "features": ["api", "webhooks", "custom_roles", "audit_log", "enforce_2fa", "custom_domain", "priority_support"]},
]


def forwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Subscription = apps.get_model("billing", "Subscription")
    Agency = apps.get_model("agencies", "Agency")
    for data in PLANS:
        Plan.objects.update_or_create(code=data["code"], defaults=data)
    pro = Plan.objects.get(code="pro")
    business = Plan.objects.get(code="business")
    for agency in Agency.objects.all():
        plan = business if agency.custom_domain else pro
        Subscription.objects.get_or_create(agency=agency, defaults={"plan": plan})


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial"), ("agencies", "0007_agency_require_2fa")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
