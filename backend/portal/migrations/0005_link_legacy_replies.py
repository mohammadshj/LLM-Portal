from django.db import migrations


def link_legacy_replies(apps, schema_editor):
    """Legacy sends were serial per chat. A turn without any reply failed."""
    Message = apps.get_model("portal", "Message")
    rows = Message.objects.using(schema_editor.connection.alias)
    rows.filter(role="user", request_id__isnull=True).update(status="failed")
    previous_chat = parent_id = None
    updates = []
    # Read just identifiers, never prompt text. Flush in bounded batches.
    for row in (
        rows.filter(parent__isnull=True, request_id__isnull=True)
        .only("id", "conversation_id", "role")
        .order_by("conversation_id", "id")
        .iterator(chunk_size=1000)
    ):
        if row.conversation_id != previous_chat:
            previous_chat, parent_id = row.conversation_id, None
        if row.role == "user":
            parent_id = row.pk
        else:
            row.parent_id = parent_id
            row.usage_source = "reported"
            updates.append(row)
        if len(updates) == 500:
            rows.bulk_update(updates, ["parent", "usage_source"])
            updates.clear()
    if updates:
        rows.bulk_update(updates, ["parent", "usage_source"])
    rows.filter(role="user", request_id__isnull=True, replies__isnull=False).update(
        status="completed"
    )


class Migration(migrations.Migration):
    # Commit schema/index creation before linking rows with deferred PostgreSQL FKs.
    dependencies = [("portal", "0004_conversation_requests")]
    operations = [migrations.RunPython(link_legacy_replies, migrations.RunPython.noop)]
