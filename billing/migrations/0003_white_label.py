from django.db import migrations


def forwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.filter(code="business"):
        if "white_label" not in plan.features:
            plan.features = plan.features + ["white_label"]
            plan.save(update_fields=["features"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0002_default_plans")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
