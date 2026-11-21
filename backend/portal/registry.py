"""Provider-scoped, durable last-good Models.dev cache, shared by all workers."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .catalog_metadata import registry_facts
from .discovery_http import DiscoveryError, read_json
from .models import RegistrySnapshot

URL = "https://models.dev/api.json"
MAX_BYTES = 64 * 1024 * 1024


def update_registry(provider, catalog=None):
    if catalog is None:
        catalog = read_json(URL, "", MAX_BYTES)
    entry = catalog.get(provider) if isinstance(catalog, dict) else None
    models = entry.get("models") if isinstance(entry, dict) else None
    if not isinstance(models, dict) or not models or len(models) > 30000:
        raise DiscoveryError("response")
    facts = {}
    for key, row in models.items():
        if (
            not isinstance(key, str)
            or not isinstance(row, dict)
            or row.get("id", key) != key
        ):
            raise DiscoveryError("response")
        facts[key] = registry_facts(row)
    snapshot, _ = RegistrySnapshot.objects.update_or_create(
        provider_id=provider, defaults={"models": facts, "fetched_at": timezone.now()}
    )
    return snapshot


def lookup(connection):
    provider = connection.registry_provider or (
        connection.discovery_type
        if connection.discovery_type in ("openai", "openrouter")
        else ""
    )
    if not provider:
        return {}, "off"
    cached = RegistrySnapshot.objects.filter(pk=provider).first()
    if settings.DISCOVERY_REGISTRY_OFFLINE:
        return (cached.models, "offline") if cached else ({}, "unavailable")
    if cached and cached.fetched_at >= timezone.now() - timedelta(days=1):
        return cached.models, "cached"
    try:
        return update_registry(provider).models, "updated"
    except DiscoveryError:
        return (cached.models, "stale") if cached else ({}, "unavailable")
