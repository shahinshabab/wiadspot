from django.core.management.base import BaseCommand

from ads.tasks import run_ad_runtime_cycle


class Command(BaseCommand):
    help = "Bill raw ad events, credit owner earnings, aggregate metrics and sync statuses. Run every minute or two."

    def handle(self, *args, **options):
        result = run_ad_runtime_cycle()
        self.stdout.write(f"billed {result['billing']['processed']} events")
