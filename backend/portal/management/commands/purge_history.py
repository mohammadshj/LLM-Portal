from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from portal.models import Conversation
from portal.services import RequestConflict, delete_conversation, recover_reservations


class Command(BaseCommand):
    help = "Delete conversations older than 30 days; preserve account usage counters."

    def handle(self, *args, **options):
        recover_reservations()
        expired = Conversation.objects.filter(
            created_at__lt=timezone.now() - timedelta(days=30)
        ).select_related("user")
        count = 0
        for conversation in expired.iterator():
            try:
                delete_conversation(conversation.user, conversation)
                count += 1
            except RequestConflict:
                continue  # May finish after crossing the retention boundary.
        self.stdout.write(f"Deleted {count} expired conversations.")
