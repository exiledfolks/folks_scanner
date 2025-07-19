from django.core.management.base import BaseCommand
from scanner.actions import run_full_scan_sync


class Command(BaseCommand):
    help = 'Run the full scan sync process for working nodes.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Starting full scan...'))
        run_full_scan_sync()
        self.stdout.write(self.style.SUCCESS('Full scan completed.'))
