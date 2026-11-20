from django.conf import settings
from django.db import migrations


def create_missing_accounts(apps, schema_editor):
    users = apps.get_model(settings.AUTH_USER_MODEL).objects.using(
        schema_editor.connection.alias
    )
    account = apps.get_model("portal", "Account")
    missing = users.filter(account__isnull=True).order_by("pk")
    for user_id in missing.values_list("pk", flat=True).iterator():
        account.objects.using(schema_editor.connection.alias).get_or_create(
            user_id=user_id
        )


class Migration(migrations.Migration):
    dependencies = [("portal", "0006_thinking_and_token_usage")]
    operations = [
        migrations.RunPython(create_missing_accounts, migrations.RunPython.noop)
    ]
