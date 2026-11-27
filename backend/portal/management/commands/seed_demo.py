from django.core.management.base import BaseCommand

from portal.models import LanguageModel


class Command(BaseCommand):
    help = "Create explicitly labeled offline demo models (no user or credential)."

    def handle(self, *args, **options):
        for name in ["مدل نمایشی الف", "مدل نمایشی ب"]:
            LanguageModel.objects.get_or_create(
                provider="demo",
                model_id=name,
                defaults={
                    "name": name,
                    "max_output_tokens": 2048,
                    "input_price_per_million_rial": 0,
                    "output_price_per_million_rial": 0,
                },
            )
        self.stdout.write("Demo models available.")
