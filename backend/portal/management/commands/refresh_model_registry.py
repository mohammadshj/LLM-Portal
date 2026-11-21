import json

from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_slug
from django.core.exceptions import ValidationError

from portal.discovery_http import DiscoveryError
from portal.registry import MAX_BYTES, update_registry


class Command(BaseCommand):
    help = "Refresh a Models.dev provider snapshot from the official catalog or a local API JSON export."

    def add_arguments(self, parser):
        parser.add_argument("provider")
        parser.add_argument("--file")

    def handle(self, *args, **options):
        catalog = None
        try:
            validate_slug(options["provider"])
            if len(options["provider"]) > 100:
                raise CommandError("شناسهٔ Provider طولانی است.")
            if options["file"]:
                with open(options["file"], "rb") as stream:
                    raw = stream.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise CommandError("کاتالوگ بیش از حد بزرگ است.")
                catalog = json.loads(raw)
                if not isinstance(catalog, dict):
                    raise CommandError("ساختار کاتالوگ معتبر نیست.")
            snap = update_registry(options["provider"], catalog)
        except (ValidationError, ValueError, RecursionError, OSError, DiscoveryError):
            raise CommandError("دریافت یا اعتبارسنجی کاتالوگ ممکن نشد.") from None
        self.stdout.write(f"{snap.provider_id}: {len(snap.models)}")
