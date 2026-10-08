"""Create demo users, reports and expenses so the system can be explored.

    python manage.py seed_demo

Passwords are random and printed once at the end (never stored in the code).
For development/demo databases only - do not run against production.
"""
import random
import secrets
from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
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
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DJANGO_DEBUG=1 (never on a live database).")
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

        _seed_operations(users, sites, rng)
        _seed_site_operations(users, sites)

        self.stdout.write(self.style.SUCCESS("Demo data created. One-time passwords (note them down now):"))
        for username, _first, _last, role, _sup in PEOPLE:
            self.stdout.write(f"  {username:<12} {role:<11} {passwords[username]}")
        self.stdout.write(f"Reports: {Report.objects.count()}  Completed: {Report.objects.filter(status=Status.COMPLETED).count()}")


def _seed_operations(users, sites, rng):
    """Made-up clients, issues, an invoice, items, item requests and a draft payroll. No emails are sent."""
    from billing import services as billing
    from billing.models import Invoice, InvoiceLine
    from clients import services as clients
    from clients.models import Client, Feedback
    from core.models import CompanySettings
    from inventory import services as inventory
    from inventory.models import Category, Item
    from payroll import services as payroll
    from payroll.models import PayProfile

    sec, mgr = users["secretary"], users["manager"]
    company = CompanySettings.load()
    company.company_name, company.phone, company.email = "Resilience Security (demo)", "0700000000", "office@example.com"
    company.address = "P.O. Box 0000, Kisumu"
    company.payment_instructions = "M-Pesa Paybill 000000, account: invoice number"
    company.save()

    acme = clients.create_client(Client(name="Lakeside Apartments", contact_person="Mr. Otieno", phone="0712000001",
                                        email="lakeside@example.com", area="Milimani", monthly_charge=Decimal("85000"),
                                        supervisor=users["supervisor1"]), sec)
    mall = clients.create_client(Client(name="Kondele Market Stores", contact_person="Mrs. Atieno", phone="0712000002",
                                        email="kondele@example.com", area="Kondele", monthly_charge=Decimal("60000"),
                                        supervisor=users["supervisor2"]), sec)
    clients.create_client(Client(name="Riverside School", phone="0712000003", area="Riat"), sec)
    clients.set_client_sites(acme, [sites[1]], sec)
    clients.set_client_sites(mall, [sites[0]], sec)

    issue = clients.create_issue(acme, "Gate light not working", "Security light at the back gate has been off for 2 nights.",
                                 "high", sec)
    clients.change_issue_status(issue, "in_progress", users["supervisor1"], "Electrician called.")
    clients.create_issue(mall, "Guard late for night shift", "The night guard arrived at 7:40 pm on Tuesday.", "normal", sec)
    Feedback.objects.create(client=mall, kind="compliment", channel="phone", subject="Thank you for quick response",
                            body="The guards stopped a break-in attempt last week.", recorded_by=sec)

    today = timezone.localdate()
    inv = Invoice(client=acme, invoice_date=today.replace(day=1), due_date=today.replace(day=1) + timedelta(days=14))
    billing.save_draft(inv, [InvoiceLine(description=f"Security services, {today:%B %Y}", quantity=1,
                                         unit_price=Decimal("85000"))], sec, creating=True)
    seq, number = billing._next_number(inv.invoice_date.year)
    Invoice.objects.filter(pk=inv.pk).update(status="sent", number=number, year=inv.invoice_date.year, seq=seq,
                                             bill_to_name=acme.name, sent_by=sec, sent_at=timezone.now())
    inv.refresh_from_db()
    billing.record_payment(inv, today, Decimal("40000"), "mpesa", "QDEMO123", sec)
    billing.save_draft(Invoice(client=mall, invoice_date=today, due_date=today + timedelta(days=14)),
                       [InvoiceLine(description="Security services", quantity=1, unit_price=Decimal("60000"))], sec, creating=True)

    def cat(name):
        return Category.objects.get_or_create(name=name)[0]

    torch = inventory.create_item(Item(name="Torch", category=cat("Torches"), returnable=True, min_stock=3), 8, sec)
    radio = inventory.create_item(Item(name="Two-way radio", category=cat("Radios"), returnable=True, min_stock=2), 4, sec)
    inventory.create_item(Item(name="Uniform shirt", category=cat("Uniforms"), returnable=False, min_stock=5), 20, sec)
    inventory.create_item(Item(name="Rain coat", category=cat("Uniforms"), returnable=True, min_stock=2), 2, sec)
    inventory.set_manager_flags([radio.pk], mgr)
    radio.refresh_from_db()
    r1 = inventory.create_request(torch, 1, "My torch stopped working.", users["staff1"])
    inventory.approve_request(r1, sec, 1, today + timedelta(days=30), hand_over_now=True)
    inventory.claim_return(r1, users["staff1"])
    inventory.create_request(torch, 2, "Night shift at Kondele.", users["staff3"])
    inventory.create_request(radio, 1, "Need to call the supervisor.", users["supervisor2"])

    for u in users.values():
        if u.role != Role.MANAGER:
            PayProfile.objects.create(user=u, basic_salary=Decimal(rng.choice([15000, 18000, 22000, 30000])),
                                      payment_method="mpesa", mpesa_number=f"07{rng.randint(10000000, 99999999)}")
    payroll.create_run(today.replace(day=1), sec)


def _seed_site_operations(users, sites):
    """Site details, attendance, leave, sick leave, the OB, a site visit and an incident."""
    from datetime import datetime

    from attendance import services as attendance
    from attendance.models import AttendanceRecord
    from incidents.models import Incident
    from incidents.services import create_incident
    from leave import services as leave
    from leave.models import LeaveType
    from operations import services as ops
    from operations.models import OBEntry

    sec, mgr = users["secretary"], users["manager"]
    details = [
        ("Off Kisumu-Kakamega Road, behind Kondele Market", users["supervisor1"], 3,
         "Check the back gate every hour. Write every vehicle in the OB.", "Kondele Police Post 0712000100"),
        ("Milimani estate, Lakeside Apartments gate", users["supervisor2"], 2,
         "No visitors after 10 pm without a call from the tenant.", "Central Police Station 0712000200"),
    ]
    for site, (address, sup, needed, rules, contacts) in zip(sites, details):
        site.address, site.supervisor, site.guards_needed = address, sup, needed
        site.instructions, site.emergency_contacts = rules, contacts
        site.save()

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    def at(day, hh, mm):
        return timezone.make_aware(datetime.combine(day, time(hh, mm)))

    for username, day, hh, mm in (("staff1", yesterday, 6, 55), ("staff3", yesterday, 7, 30), ("supervisor1", yesterday, 6, 50)):
        user = users[username]
        late = max(0, (hh * 60 + mm) - (7 * 60 + 15))
        AttendanceRecord.objects.create(
            user=user, date=day, site=user.tracking.site, supervisor=attendance.approver_for(user),
            outcome="late" if late else "present", status="waiting_manager", method="gps", signed_in_at=at(day, hh, mm),
            shift_start=at(day, 7, 0), late_minutes=late + 15 if late else 0, distance_m=12, location_status="on",
        )
    if yesterday.weekday() < 6:
        attendance.complete_day(yesterday, mgr)
    if today.weekday() < 6:
        for username, status in (("staff1", "waiting_supervisor"), ("supervisor2", "waiting_manager")):
            user = users[username]
            AttendanceRecord.objects.create(
                user=user, date=today, site=user.tracking.site, supervisor=attendance.approver_for(user), outcome="present",
                status=status, method="gps", signed_in_at=at(today, 6, 50), shift_start=at(today, 7, 0),
                distance_m=9, location_status="on",
            )

    annual = LeaveType.objects.get(code="annual")
    leave.ask_for_leave(users["staff2"], annual, today + timedelta(days=14), today + timedelta(days=18), "Family visit", users["staff2"])
    leave.ask_for_leave(users["staff4"], annual, today, today + timedelta(days=2), "Wedding", users["supervisor2"])
    leave.report_sick(users["staff3"], today, today + timedelta(days=1), "", users["supervisor2"])

    ops.write_ob(sites[0], users["staff1"], OBEntry.Kind.SHIFT_START, "Shift started. All in order.", at(today, 7, 0))
    ops.write_ob(sites[0], users["staff1"], OBEntry.Kind.VISITOR, "Water bowser KCA 123B delivered water.", at(today, 9, 20))
    ops.record_visit(sites[0], users["supervisor1"], at(today, 10, 0), ["guards_at_post", "uniform", "ob_up_to_date"],
                     [users["staff1"]], True, "All fine. Asked for a new torch battery.")
    create_incident(Incident(site=sites[1], occurred_at=at(yesterday, 23, 40), kind="trespass", severity="medium",
                             what_happened="Two people climbed the back fence and ran off when challenged.",
                             who_involved="Two unknown men", action_taken="Raised the alarm, called the supervisor.",
                             police_reported=True, police_ob_number="OB 12/08/2026", client_told=True), users["staff4"])
    Report.objects.create(author=sec, title="Fuel prices went up this month", body="The generator fuel bill is 12% higher.")
