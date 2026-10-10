"""Everything that needs a person, as one action list ("N things need you").

Each to-do says who it comes from (a coloured sender chip), what it is, the one verb to do about it
(report section 6.2) and what happens next. The verbs that need no typing (Approve this, Solve this)
work straight from the row through a POST with a confirmation; the others open the record.

Each source is one query, so the home pages stay light.
"""
from dataclasses import dataclass, field

from django.urls import reverse

from accounts.models import Role

# How many rows one source shows on a home page before "See all".
LIMIT = 20

# Who it comes from, in the order the groups are shown.
GROUPS = (
    ("manager", "From the Manager"),
    ("secretary", "From the Secretary"),
    ("supervisor", "From supervisors"),
    ("staff", "From guards"),
    ("client", "From clients"),
    ("system", "From the system"),
)

# Notification kinds whose subject is already a to-do somewhere, so the bell does not show them twice.
TODO_KINDS = {
    "leave.request", "request.new", "request.manager_needed", "request.return_claimed", "report.new",
    "issue.assigned", "issue.supervisor_needed", "client.supervisor_needed", "payroll.submitted",
    "expense.approval", "escalation.new", "escalation.sent_back", "escalation.reply", "incident.new",
    "sick.sheet", "report.reply",
}
# Of those, the ones that are themselves the to-do ("Read this") until opened.
READ_KINDS = ("report.reply", "escalation.reply")


@dataclass
class Action:
    label: str
    url: str = ""          # a link (opens the record)
    post: str = ""         # or a one-tap POST
    style: str = ""
    confirm: str = ""
    fields: tuple = ()


@dataclass
class Todo:
    sender: object          # a User, a Client, or "system"
    summary: str
    url: str
    actions: list = field(default_factory=list)
    next: str = ""
    when: object = None
    urgent: bool = False

    @property
    def kind(self):
        from core.templatetags.ui import sender_kind

        return sender_kind(self.sender)

    @property
    def sender_css(self):
        from core.templatetags.ui import SENDERS

        return SENDERS.get(self.kind, SENDERS["system"])[0]


def approve(url, confirm, label="Approve this"):
    return Action(label, post=url, confirm=confirm)


def open_(label, url="", style=""):
    return Action(label, url=url, style=style)


# --- one function per source -------------------------------------------------------------------

def _escalations_for_manager():
    from escalations.models import Escalation

    qs = Escalation.objects.filter(status__in=(Escalation.Status.OPEN, Escalation.Status.SEEN)).select_related("raised_by")
    for e in qs.order_by("raised_at")[:LIMIT]:
        url = reverse("escalations:detail", args=[e.pk])
        yield Todo(e.raised_by, f"{e.get_kind_display()}: {e.subject}", url, [open_("Reply to this")],
                   "Your answer goes back to the Secretary.", e.raised_at)


def _payroll_for_manager():
    from payroll.models import PayrollRun

    qs = PayrollRun.objects.filter(status__in=(PayrollRun.Status.SUBMITTED, PayrollRun.Status.UNDER_REVIEW)).select_related("submitted_by")
    for r in qs:
        yield Todo(r.submitted_by or "system", f"Payroll for {r.period:%B %Y}: net KES {r.total_net:,.2f}",
                   r.get_absolute_url(), [open_("Approve this")],
                   "Open it to approve, ask for changes or say no.", r.submitted_at)


def _items_for_manager():
    from inventory.models import ItemRequest

    qs = ItemRequest.objects.filter(status=ItemRequest.Status.AWAITING_MANAGER).select_related("item", "requester")
    for r in qs.order_by("created_at")[:LIMIT]:
        url = r.get_absolute_url()
        yield Todo(r.requester, f"Asked for {r.qty_requested} × {r.item.name}", url,
                   [approve(reverse("inventory:manager_approve", args=[r.pk]), f"Approve {r.qty_requested} × {r.item.name}?"),
                    open_("Say no", url, "secondary")],
                   "Approved: the Secretary hands it out. Say no: they are told why.", r.created_at)


def _expenses_for_manager():
    from finance.models import Expense

    qs = Expense.objects.filter(status=Expense.Status.AWAITING_APPROVAL).select_related("recorded_by", "category")
    for e in qs.order_by("date")[:LIMIT]:
        url = e.get_absolute_url()
        yield Todo(e.recorded_by, f"Expense above the limit: {e.description} (KES {e.amount:,.2f})", url,
                   [approve(reverse("finance:approve", args=[e.pk]), f"Approve KES {e.amount:,.2f}?"), open_("Say no", url, "secondary")],
                   "The Secretary is told at once.", e.created_at)


def _leave_to_decide(user):
    from django.db.models import Q

    from leave.models import LeaveRequest

    qs = LeaveRequest.objects.filter(status=LeaveRequest.Status.WAITING).select_related("user", "leave_type")
    if user.role == Role.MANAGER:
        qs = qs.exclude(user=user).filter(Q(approver__isnull=True) | ~Q(approver__is_active=True) | Q(approver=user))
    else:
        qs = qs.filter(approver=user)
    for r in qs.order_by("start_date")[:LIMIT]:
        yield Todo(r.user, f"{r.leave_type.name}: {r.start_date:%d %b} to {r.end_date:%d %b}", r.get_absolute_url(),
                   [open_("Approve this")], "Open it to approve or say no. They are told at once.", r.created_at)


def _attendance_day_for_manager(board):
    if board and board.get("waiting_manager") and not board.get("completed"):
        n = board["waiting_manager"]
        yield Todo("system", f"{n} sign-in{'s' if n != 1 else ''} approved by supervisors: complete the day",
                   reverse("attendance:day"), [open_("Complete this")],
                   "Everyone else is then recorded as absent, on leave or sick.")


def _incidents_for_manager():
    from incidents.models import Incident

    S = Incident.Status
    qs = (Incident.objects.exclude(status=S.CLOSED).select_related("site", "reported_by")
          .order_by("-occurred_at"))
    for i in qs[:LIMIT]:
        serious = i.serious
        if serious and i.status in (S.REPORTED, S.SUPERVISOR_REVIEWED):
            yield Todo(i.reported_by, f"{i.get_severity_display()} incident {i.number}: {i.get_kind_display()} at {i.site}",
                       i.get_absolute_url(), [open_("Read this")], "Mark it reviewed, then close it when it is finished.",
                       i.occurred_at, urgent=True)
        elif i.status in (S.SUPERVISOR_REVIEWED, S.MANAGER_REVIEWED):
            yield Todo(i.reported_by, f"Incident {i.number} at {i.site} is ready to close", i.get_absolute_url(),
                       [open_("Check this")], "Close it when nothing more is needed.", i.occurred_at)


def _reports_for(user):
    """Reports sent to this person that are not solved yet."""
    from reports.models import Report, Status

    qs = Report.objects.exclude(status=Status.COMPLETED).select_related("author")
    if user.role == Role.MANAGER:
        qs = qs.filter(author__role__in=(Role.SUPERVISOR, Role.SECRETARY))
    else:
        qs = qs.filter(author__supervisor=user, status=Status.PENDING)
    for r in qs.order_by("created_at")[:LIMIT]:
        url = r.get_absolute_url()
        yield Todo(r.author, r.title, url,
                   [open_("Reply to this"),
                    approve(reverse("reports:resolve", args=[r.pk]), "Mark this report solved?", "Solve this")],
                   "Your reply is sent to them at once.", r.created_at)


def _issues_for_supervisor(user):
    from clients.models import Issue
    from clients.services import OPEN_ISSUE_STATUSES

    qs = Issue.objects.filter(supervisor=user, status__in=OPEN_ISSUE_STATUSES).select_related("client")
    for i in qs.order_by("created_at")[:LIMIT]:
        yield Todo(i.client, f"{i.number}: {i.subject}", i.get_absolute_url(), [open_("Solve this")],
                   "Add a note, then mark it resolved. The office closes it with the client.", i.created_at,
                   urgent=i.priority in (Issue.Priority.HIGH, Issue.Priority.URGENT))


def _signins_for_supervisor(user):
    from attendance.models import AttendanceRecord

    qs = AttendanceRecord.objects.filter(supervisor=user, status=AttendanceRecord.Status.WAITING_SUPERVISOR).select_related("user", "site")
    for rec in qs.order_by("date", "signed_in_at")[:LIMIT]:
        when = rec.signed_in_at
        text = f"Signed in at {rec.site}" if rec.site else "Signed in"
        if when:
            from django.utils import timezone

            text += f" at {timezone.localtime(when):%H:%M} on {rec.date:%a %d %b}"
        if rec.late_minutes:
            text += f" ({rec.late_minutes} min late)"
        yield Todo(rec.user, text, reverse("attendance:team") + f"?date={rec.date}",
                   [approve(reverse("attendance:approve", args=[rec.pk]), f"Approve {rec.user}'s sign-in?"),
                    open_("Say no", reverse("attendance:team") + f"?date={rec.date}", "secondary")],
                   "Approved sign-ins go to the Manager, who completes the day.", when)


def _incidents_for_supervisor(user):
    from incidents import services
    from incidents.models import Incident

    qs = (Incident.objects.visible_to(user).filter(status=Incident.Status.REPORTED).exclude(reported_by=user)
          .select_related("site", "reported_by"))
    for i in qs.order_by("-occurred_at")[:LIMIT]:
        if services.can_supervisor_review(i, user):
            yield Todo(i.reported_by, f"{i.get_severity_display()} incident {i.number}: {i.get_kind_display()} at {i.site}",
                       i.get_absolute_url(), [open_("Check this")], "Add a note and mark it reviewed.",
                       i.occurred_at, urgent=i.serious)


def _secretary_items():
    from inventory.models import ItemRequest

    R = ItemRequest.Status
    qs = (ItemRequest.objects.filter(status__in=(R.PENDING, R.READY, R.RETURN_CLAIMED))
          .select_related("item", "requester").order_by("created_at"))
    for r in qs[:LIMIT * 2]:
        url = r.get_absolute_url()
        if r.status == R.PENDING:
            yield Todo(r.requester, f"Asked for {r.qty_requested} × {r.item.name}", url,
                       [open_("Approve this"), open_("Say no", url, "secondary")],
                       "Approve to keep it aside or hand it over now. Say no with a reason.", r.created_at)
        elif r.status == R.READY:
            yield Todo(r.requester, f"Ready to collect: {r.qty_issued or r.qty_requested} × {r.item.name}", url,
                       [open_("Hand out")], "Hand it over when they come.", r.created_at)
        else:
            yield Todo(r.requester, f"Says they returned {r.item.name}", url, [open_("Check this")],
                       "Stock only moves when you confirm you have it.", r.created_at)


def _secretary_clients():
    from clients.models import Feedback, Issue, Message

    from clients.models import Client

    no_sup = Client.objects.filter(is_active=True, supervisor__isnull=True).count()
    if no_sup:
        yield Todo("system", f"{no_sup} client{'s have' if no_sup != 1 else ' has'} no supervisor",
                   reverse("clients:list") + "?supervisor=none", [open_("Solve this")],
                   "Choose a supervisor so their issues reach someone.")
    for i in Issue.objects.filter(status=Issue.Status.SUPERVISOR_NEEDED).select_related("client")[:LIMIT]:
        yield Todo(i.client, f"{i.number}: {i.subject}: no supervisor yet", i.get_absolute_url(),
                   [open_("Solve this")], "Choose a supervisor; they are told at once.", i.created_at, urgent=True)
    for i in Issue.objects.filter(status=Issue.Status.RESOLVED).select_related("client", "supervisor")[:LIMIT]:
        yield Todo(i.supervisor or i.client, f"{i.number}: {i.subject} ({i.client}) is resolved",
                   i.get_absolute_url(), [open_("Check this")], "Check with the client, then close it.", i.resolved_at)
    for fb in Feedback.objects.filter(status=Feedback.Status.NEW).select_related("client")[:LIMIT]:
        yield Todo(fb.client, f"{fb.get_kind_display()}: {fb.subject}", fb.get_absolute_url(),
                   [open_("Read this")], "Answer it, pass it to the Manager or turn it into an issue.", fb.recorded_at)
    for m in Message.objects.filter(status=Message.Status.FAILED).select_related("client")[:LIMIT]:
        yield Todo("system", f"Email to {m.client} did not send: {m.subject}", m.get_absolute_url(),
                   [open_("Check this")], "Try again, or record that you told them by phone.", m.created_at)


def _secretary_from_manager():
    from escalations.models import Escalation
    from payroll.models import PayrollRun

    for e in Escalation.objects.filter(status=Escalation.Status.SENT_BACK).select_related("resolved_by")[:LIMIT]:
        yield Todo(_a_manager(), f"Sent back to you: {e.subject}", reverse("escalations:detail", args=[e.pk]),
                   [open_("Reply to this")], "Add what the Manager asked for and send it again.", e.raised_at)
    run = PayrollRun.objects.filter(status=PayrollRun.Status.REVISION_REQUIRED).select_related("decided_by").first()
    if run:
        yield Todo(run.decided_by or _a_manager(), f"Asked for changes to payroll for {run.period:%B %Y}",
                   run.get_absolute_url(), [open_("Complete this")], run.decision_note[:120], run.decided_at)


def _sick_sheets():
    from leave.models import SickLeave

    qs = SickLeave.objects.filter(status=SickLeave.Status.CERTIFICATE_RECEIVED).select_related("user")
    for s in qs.order_by("first_day")[:LIMIT]:
        yield Todo(s.user, f"Sick sheet for {s.first_day:%d %b} to {s.last_day:%d %b}", s.get_absolute_url(),
                   [open_("Check this")], "Accept it, or ask for it again.", s.updated_at)


def _secretary_system():
    from django.db.models import F
    from django.utils import timezone

    from billing.models import Invoice
    from inventory.models import Item
    from inventory.services import overdue_requests

    overdue = Invoice.objects.filter(status=Invoice.Status.OVERDUE).count()
    if overdue:
        yield Todo("system", f"{overdue} invoice{'s are' if overdue != 1 else ' is'} overdue",
                   reverse("billing:list") + "?status=overdue", [open_("Check this")],
                   "Remind the client or record a payment.")
    low = Item.objects.filter(is_active=True, min_stock__gt=0, qty_available__lte=F("min_stock")).count()
    if low:
        yield Todo("system", f"{low} item{'s are' if low != 1 else ' is'} low on stock",
                   reverse("inventory:library") + "?stock=low", [open_("Check this")], "Buy more or change the minimum.")
    late = overdue_requests(timezone.localdate()).count()
    if late:
        yield Todo("system", f"{late} item{'s are' if late != 1 else ' is'} overdue for return", reverse("inventory:overdue"),
                   [open_("Check this")], "A reminder goes out once a day.")


def _unread_replies(user):
    """Replies to my reports or matters that I have not read yet ("Read this"). Opening one marks it read."""
    from notifications.models import Notification

    for n in Notification.objects.filter(recipient=user, read_at__isnull=True, kind__in=READ_KINDS)[:LIMIT]:
        yield Todo(_reply_author(n) or "system", n.title, reverse("notifications:open", args=[n.pk]),
                   [open_("Read this", reverse("notifications:open", args=[n.pk]))], "", n.created_at)


def _my_items(user):
    from inventory.models import ItemRequest

    for r in ItemRequest.objects.filter(requester=user, status=ItemRequest.Status.READY).select_related("item"):
        yield Todo("system", f"{r.item.name} is ready: collect it from the Secretary",
                   reverse("inventory:mine_detail", args=[r.pk]), [open_("Read this")], "", r.updated_at)


def _a_manager():
    from accounts.models import User

    return User.objects.filter(role=Role.MANAGER, is_active=True).order_by("pk").first() or "manager"


def _reply_author(note):
    from reports.models import Reply

    if note.kind == "report.reply" and note.entity_id.isdigit():
        reply = Reply.objects.filter(report_id=int(note.entity_id)).select_related("author").order_by("-created_at").first()
        return reply.author if reply else None
    return _a_manager() if note.kind == "escalation.reply" else None


# --- per role ----------------------------------------------------------------------------------

def todos_for(user, board=None):
    """The to-do list for one person (newest last within each sender group)."""
    role = user.role
    sources = []
    if role == Role.MANAGER:
        sources = [_incidents_for_manager(), _escalations_for_manager(), _payroll_for_manager(), _items_for_manager(),
                   _expenses_for_manager(), _leave_to_decide(user), _reports_for(user),
                   _attendance_day_for_manager(board)]
    elif role == Role.SECRETARY:
        sources = [_secretary_from_manager(), _unread_replies(user), _secretary_items(), _sick_sheets(),
                   _secretary_clients(), _secretary_system()]
    elif role == Role.SUPERVISOR:
        sources = [_signins_for_supervisor(user), _reports_for(user), _incidents_for_supervisor(user),
                   _issues_for_supervisor(user), _leave_to_decide(user), _unread_replies(user), _my_items(user)]
    else:
        sources = [_unread_replies(user), _my_items(user)]
    return [t for source in sources for t in source]


def grouped(todos):
    """[(label, [todo, ...]), ...] in the fixed sender order, empty groups left out."""
    by_kind = {}
    for t in todos:
        by_kind.setdefault(t.kind, []).append(t)
    return [(label, by_kind[kind]) for kind, label in GROUPS if by_kind.get(kind)]


def context(user, board=None):
    todos = todos_for(user, board)
    return {"todos": todos, "todo_groups": grouped(todos), "todo_count": len(todos)}
