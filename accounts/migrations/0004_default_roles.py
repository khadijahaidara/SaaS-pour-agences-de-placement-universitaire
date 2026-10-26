from django.db import migrations


def forwards(apps, schema_editor):
    from accounts.rbac import DEFAULT_ROLE_KEY, DEFAULT_ROLES

    Role = apps.get_model("accounts", "Role")
    Agency = apps.get_model("agencies", "Agency")
    User = apps.get_model("accounts", "User")
    for agency in Agency.objects.all():
        for key, name, description, perms in DEFAULT_ROLES:
            Role.objects.get_or_create(agency=agency, key=key, defaults={
                "name": name, "description": description, "permissions": perms, "is_system": key == DEFAULT_ROLE_KEY})
        default = Role.objects.get(agency=agency, key=DEFAULT_ROLE_KEY)
        User.objects.filter(agency=agency, role="counselor", agency_role__isnull=True).update(agency_role=default)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_roles_2fa_sessions")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
