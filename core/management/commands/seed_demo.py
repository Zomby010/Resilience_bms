"""Create demo users, reports and expenses so the system can be explored.

    python manage.py seed_demo

Passwords are random and printed once at the end (never stored in the code).
For development/demo databases only - do not run against production.
"""
import random
import secrets
from datetime import time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, User
from finance.models import Expense, ExpenseCategory, ExpenseLog
from reports.models import Report, Status
from tracking.models import Site, TrackingProfile, WorkHours

PEOPLE = [
    # username, first, last, role, supervisor username
    ("manager", "Mary", "Manager", Role.MANAGER, None),
    ("supervisor1", "Samuel", "Otieno", Role.SUPERVISOR, None),
    ("supervisor2", "Sarah", "Achieng", Role.SUPERVISOR, None),
    ("staff1", "Peter", "Odhiambo", Role.STAFF, "supervisor1"),
    ("staff2", "Grace", "Wanjiru", Role.STAFF, "supervisor1"),
    ("staff3", "James", "Kiplagat", Role.STAFF, "supervisor2"),
    ("staff4", "Amina", "Hassan", Role.STAFF, "supervisor2"),
    ("secretary", "Susan", "Secretary", Role.SECRETARY, None),
]

TITLES = [
    "Night patrol summary",
    "Alarm system fault at client site",
    "Guard shift handover issues",
    "Equipment request: torches and radios",
    "Incident report: attempted break-in",
    "Weekly site inspection",
]

CATEGORIES = ["Fuel", "Uniforms", "Equipment", "Office supplies", "Transport", "Salaries & wages", "Utilities"]


class Command(BaseCommand):
    help = "Create demo users, reports and expenses (development only)."

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(username="manager").exists():
            raise CommandError("Demo data already exists (user 'manager' found). Aborting.")

        rng = random.Random(42)
        now = timezone.now()
        passwords, users = {}, {}

        for username, first, last, role, sup in PEOPLE:
            password = secrets.token_urlsafe(10)
            user = User(
                username=username, first_name=first, last_name=last, role=role,
                email=f"{username}@example.com", supervisor=users.get(sup),
            )
            user.set_password(password)
            user.save()
            users[username], passwords[username] = user, password

        staff = [u for u in users.values() if u.role == Role.STAFF]
        for i in range(24):
            author = rng.choice(staff + [users["supervisor1"], users["supervisor2"]])
            report = Report.objects.create(
                author=author,
                title=rng.choice(TITLES),
                body="Sample report text for demonstration purposes.\nPlease review and advise.",
            )
            created = now - timedelta(days=rng.randint(0, 170))
            Report.objects.filter(pk=report.pk).update(created_at=created)
            report.refresh_from_db()
            roll = rng.random()
            if author.role == Role.STAFF and roll > 0.3:
                report.add_reply(author.supervisor, "Reviewed - thanks. Please follow the standard procedure.")
            if roll > 0.55:
                report.add_reply(users["manager"], "Noted. Thank you for the update.", complete=True)

        cats = [ExpenseCategory.objects.create(name=n) for n in CATEGORIES]
        for _ in range(40):
            expense = Expense.objects.create(
                date=timezone.localdate() - timedelta(days=rng.randint(0, 120)),
                category=rng.choice(cats),
                description=rng.choice(["Monthly purchase", "Top-up", "Replacement", "Supplier payment"]),
                amount=Decimal(rng.randint(500, 45000)),
                reference=f"RCPT-{rng.randint(1000, 9999)}",
                recorded_by=users["secretary"],
            )
            ExpenseLog.record(expense, ExpenseLog.Action.CREATED, users["secretary"])

        # Two GPS work sites in Kisumu, weekday day shifts, everyone assigned.
        sites = [
            Site.objects.create(name="Kondele Site", latitude=Decimal("-0.083300"), longitude=Decimal("34.772500")),
            Site.objects.create(name="Milimani Site", latitude=Decimal("-0.101500"), longitude=Decimal("34.752800")),
        ]
        for site in sites:
            WorkHours.objects.bulk_create(
                [WorkHours(site=site, weekday=d, start=time(7), end=time(18)) for d in range(6)]
            )
        for i, username in enumerate(["supervisor1", "staff1", "staff2", "supervisor2", "staff3", "staff4"]):
            TrackingProfile.objects.create(user=users[username], site=sites[0 if i < 3 else 1])

        self.stdout.write(self.style.SUCCESS("Demo data created. One-time passwords (note them down now):"))
        for username, _first, _last, role, _sup in PEOPLE:
            self.stdout.write(f"  {username:<12} {role:<11} {passwords[username]}")
        self.stdout.write(f"Reports: {Report.objects.count()}  Completed: {Report.objects.filter(status=Status.COMPLETED).count()}")
