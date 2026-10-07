"""Check working hours, open/close location alerts, and delete old location history.

The manager's GPS Tracker page does the same check every 15 seconds while it is
open. Run this every few minutes from a scheduler (cron, Windows Task Scheduler
or your host's "scheduled jobs") so alerts and clean-up also happen when nobody
has the page open:

    python manage.py check_tracking
"""
from django.core.management.base import BaseCommand

from tracking import services


class Command(BaseCommand):
    help = "Update location alerts and delete location history older than the retention period."

    def handle(self, *args, **options):
        services.ensure_profiles()
        services.evaluate_alerts()
        deleted = services.purge_history()
        self.stdout.write(f"Alerts checked. Deleted {deleted} old location record(s).")
