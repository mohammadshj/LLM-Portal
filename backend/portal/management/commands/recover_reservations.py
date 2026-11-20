from django.core.management.base import BaseCommand

from portal.services import recover_reservations


class Command(BaseCommand):
    help = "Release abandoned LLM reservations after their owner lease expires."

    def handle(self, *args, **options):
        self.stdout.write(f"Recovered {recover_reservations()} expired turns.")
