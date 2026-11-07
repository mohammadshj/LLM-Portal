from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from portal.models import Conversation


class Command(BaseCommand):
    help = "Delete conversations older than 30 days; preserve account usage counters."

    def handle(self, *args, **options):
        count, _ = Conversation.objects.filter(
            created_at__lt=timezone.now() - timedelta(days=30)
        ).delete()
        self.stdout.write(f"Deleted {count} expired records.")
