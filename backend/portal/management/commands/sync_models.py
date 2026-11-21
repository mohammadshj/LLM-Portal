from django.core.management.base import BaseCommand, CommandError

from portal.discovery import sync_models
from portal.discovery_http import DiscoveryError
from portal.models import ModelConnection


class Command(BaseCommand):
    help = "Synchronize one saved provider connection, using the same policy as Django Admin."

    def add_arguments(self, parser):
        parser.add_argument("connection_id", type=int)

    def handle(self, *args, **options):
        try:
            result = sync_models(options["connection_id"])
        except ModelConnection.DoesNotExist:
            raise CommandError("اتصال پیدا نشد.") from None
        except DiscoveryError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(str(result))
        if result["errors"]:
            raise CommandError("برخی ردیف‌های فهرست معتبر نبودند.")
