"""Fetch outside transactions, then reconcile one connection's exact model IDs."""

import logging
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import registry
from .capabilities import connection_signature
from .catalog_metadata import provider_facts
from .discovery_http import DiscoveryError, credential, read_json
from .models import LanguageModel, ModelConnection

logger = logging.getLogger(__name__)


def clean_text(value, limit):
    return (
        isinstance(value, str)
        and 0 < len(value) <= limit
        and value.strip() == value
        and value.isprintable()
    )


def contains_credential(value, key):
    if isinstance(value, dict):
        return any(key in k or contains_credential(v, key) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_credential(v, key) for v in value)
    return isinstance(value, str) and key in value


def listing(connection):
    key = credential(connection)
    base = connection.base_url.rstrip("/")
    kind = connection.discovery_type
    if kind == "ollama":
        path, field = base.removesuffix("/v1") + "/api/tags", "models"
    elif kind == "lmstudio":
        path, field = base.removesuffix("/v1") + "/api/v1/models", "models"
    elif kind == "openrouter":
        path, field = base + "/models/user", "data"
    elif kind in ("compatible", "openai"):
        path, field = base + "/models", "data"
    else:
        raise DiscoveryError("endpoint")
    params = {"output_modalities": "all"} if kind == "openrouter" else None
    data = read_json(path, key, 8 * 1024 * 1024, params=params)
    if isinstance(data, dict) and any(
        data.get(key)
        for key in ("has_more", "next", "next_page_token", "nextPageToken")
    ):
        # A vendor continuation URL is not an authorized credential destination.
        # Leave the previous inventory intact rather than importing an incomplete list.
        raise DiscoveryError("pagination")
    rows = data.get(field) if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > 5000:
        raise DiscoveryError("response")
    entries, errors = {}, []
    duplicates = 0
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errors.append({"row": index, "code": "invalid_entry"})
            continue
        if kind == "ollama":
            ident = row.get("model", row.get("name"))
        elif kind == "lmstudio":
            ident = row.get("key")
        else:
            ident = row.get("id")
        if not clean_text(ident, 150) or (key and key in ident):
            errors.append({"row": index, "code": "invalid_id"})
            continue
        if ident in entries:
            duplicates += 1
            continue
        name = row.get("name", row.get("display_name"))
        if not clean_text(name, 100) or (key and key in name):
            name = ident[:100]
        facts = provider_facts(row, kind)
        if key and contains_credential(facts, key):
            errors.append({"row": index, "code": "invalid_metadata"})
            continue
        entries[ident] = (name, facts, index)
    return entries, errors, duplicates


def sync_models(pk):
    started = timezone.now()
    with transaction.atomic():
        conn = ModelConnection.objects.select_for_update().get(pk=pk)
        if not conn.enabled:
            raise DiscoveryError("disabled")
        if (
            conn.sync_result.get("status") == "running"
            and conn.sync_started_at
            and conn.sync_started_at > started - timedelta(minutes=5)
        ):
            raise DiscoveryError("busy")
        conn.sync_started_at, conn.sync_result = started, {"status": "running"}
        conn.save(update_fields=["sync_started_at", "sync_result"])
    try:
        entries, errors, duplicates = listing(conn)
        catalog, cache = registry.lookup(conn)
        with transaction.atomic():
            current = ModelConnection.objects.select_for_update().get(pk=pk)
            signature = connection_signature(conn)
            if (
                current.sync_started_at != started
                or not current.enabled
                or connection_signature(current) != signature
            ):
                raise DiscoveryError("changed")
            existing = defaultdict(list)
            for model in LanguageModel.objects.select_for_update().filter(
                connection=current
            ):
                existing[model.model_id].append(model)
            new, changed = [], []
            unchanged = 0
            for ident, (name, provider, row) in entries.items():
                matches = existing.get(ident, [])
                if len(matches) > 1:
                    errors.append({"row": row, "code": "existing_duplicates"})
                    continue
                model = (
                    matches[0]
                    if matches
                    else LanguageModel(
                        connection=current,
                        provider="openai",
                        model_id=ident,
                        name=name,
                        enabled=False,
                        auto_thinking=True,
                        output_parameter="max_completion_tokens"
                        if current.discovery_type == "openai"
                        else "max_tokens",
                    )
                )
                old = model.discovery_data
                managed_name = not matches or (
                    old.get("managed_name", False) and model.name == old.get("name")
                )
                data = {
                    "model_id": ident,
                    "name": name,
                    "managed_name": managed_name,
                    "connection": signature,
                    "provider": provider,
                    "registry": old.get("registry", {})
                    if cache == "unavailable"
                    and old.get("connection") == signature
                    and old.get("model_id") == ident
                    else catalog.get(ident, {}),
                }
                if old == data:
                    unchanged += 1
                    continue
                if managed_name:
                    model.name = name
                model.discovery_data = data
                (changed if matches else new).append(model)
            LanguageModel.objects.bulk_create(new, batch_size=100)
            if changed:
                LanguageModel.objects.bulk_update(
                    changed, ["name", "discovery_data"], batch_size=100
                )
            result = {
                "status": "partial" if errors else "ok",
                "added": len(new),
                "updated": len(changed),
                "unchanged": unchanged,
                "absent": sum(
                    len(ms) for ident, ms in existing.items() if ident not in entries
                ),
                "duplicates": duplicates,
                "errors": len(errors),
                "issues": errors[:25],
                "registry": cache,
            }
            current.sync_result, current.last_synced_at = result, timezone.now()
            current.save(update_fields=["sync_result", "last_synced_at"])
            return result
    except DiscoveryError as exc:
        ModelConnection.objects.filter(pk=pk, sync_started_at=started).update(
            sync_result={
                "status": "failed",
                "code": exc.code,
                "http_status": exc.status,
            }
        )
        raise
    except Exception as exc:
        logger.error(
            "model_discovery_internal connection_id=%s error_class=%s",
            pk,
            type(exc).__name__,
        )
        ModelConnection.objects.filter(pk=pk, sync_started_at=started).update(
            sync_result={"status": "failed", "code": "internal"}
        )
        raise DiscoveryError("internal") from None
