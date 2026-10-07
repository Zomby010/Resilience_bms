from django.core.management.base import BaseCommand

from core.checks import run_daily_checks


class Command(BaseCommand):
    help = "Mark overdue invoices and send reminders for overdue items. Safe to run more than once a day."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even if the checks already ran today.")

    def handle(self, *args, **options):
        result = run_daily_checks(force=options["force"])
        if result is None:
            self.stdout.write("Checks already ran today. Use --force to run again.")
            return
        self.stdout.write(self.style.SUCCESS(
            f"Done. {result['overdue_invoices']} invoice(s) marked overdue, {result['item_reminders']} item reminder(s) sent."
        ))
