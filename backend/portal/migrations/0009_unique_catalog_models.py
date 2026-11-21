from django.db import migrations, models


def preserve_existing_aliases(apps, schema_editor):
    table = apps.get_model("portal", "LanguageModel").objects.using(
        schema_editor.connection.alias
    )
    duplicates = (
        table.exclude(connection_id=None)
        .order_by()
        .values("connection_id", "model_id")
        .annotate(n=models.Count("pk"))
        .filter(n__gt=1)
    )
    for group in duplicates:
        rows = table.filter(
            connection_id=group["connection_id"], model_id=group["model_id"]
        )
        first = rows.order_by("pk").values_list("pk", flat=True).first()
        rows.exclude(pk=first).update(legacy_alias=True)


class Migration(migrations.Migration):
    dependencies = [("portal", "0008_model_discovery")]
    operations = [
        migrations.AddField(
            model_name="languagemodel",
            name="legacy_alias",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.RunPython(preserve_existing_aliases, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="languagemodel",
            constraint=models.UniqueConstraint(
                fields=["connection", "model_id"],
                condition=models.Q(legacy_alias=False, connection__isnull=False),
                name="unique_connection_catalog_model",
            ),
        ),
    ]
