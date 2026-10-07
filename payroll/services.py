"""Payroll rules. Everything here is confidential: audit entries are marked so, and only the
Secretary and Manager can reach any page that calls these functions."""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from core.services import audit
from core.workflow import TransitionError, advance
from notifications.models import Notification
from notifications.services import notify, notify_role

from .models import PayProfile, PayrollLine, PayrollRun

S = PayrollRun.Status
EDITABLE = (S.DRAFT, S.REVISION_REQUIRED)
DECIDABLE = (S.SUBMITTED, S.UNDER_REVIEW)
EARNINGS = ("basic", "allowances", "overtime", "bonus")
DEDUCTIONS = ("paye", "shif", "nssf", "housing_levy", "advance", "other_deductions")
PROFILE_FIELDS = ["basic_salary", "regular_allowances", "allowance_note", "payment_method", "mpesa_number",
                  "bank_name", "bank_account", "is_active"]


def payable_people():
    """Active accounts that can be paid. Managers are never in payroll (owner decision D4)."""
    return User.objects.filter(is_active=True).exclude(role=Role.MANAGER)


def _log(user, action, obj, summary, changes=None):
    audit.record(user, action, obj, summary, changes=changes, confidential=True)


def link(run):
    return reverse("payroll:detail", args=[run.pk])


# --- pay profiles -------------------------------------------------------------

@transaction.atomic
def save_profile(profile, user, before):
    if profile.user.role == Role.MANAGER:
        raise TransitionError("Managers are not included in payroll.")
    profile.updated_by = user
    profile.save()
    changes = audit.changes_between(before, audit.snapshot(profile, PROFILE_FIELDS))
    for f in ("mpesa_number", "bank_account"):  # never write full account numbers into the log
        if f in changes:
            changes[f] = ["(changed)", "(changed)"]
    _log(user, "payroll.profile_saved", profile, f"Updated pay details for {profile.user}", changes)
    return profile


def payment_detail(profile):
    if profile is None:
        return "", ""
    if profile.payment_method == "mpesa":
        return profile.payment_method, profile.mpesa_number
    if profile.payment_method == "bank":
        return profile.payment_method, f"{profile.bank_name} {profile.bank_account}".strip()
    return profile.payment_method, ""


# --- runs -----------------------------------------------------------------------

def employee_number(u):
    return f"EMP-{u.pk:04d}"


def _line_for(run, u):
    profile = PayProfile.objects.filter(user=u).first()
    method, detail = payment_detail(profile)
    line = PayrollLine(
        run=run, employee=u, employee_name=str(u)[:150], employee_number=employee_number(u), role=u.role,
        basic=profile.basic_salary if profile else Decimal("0"),
        allowances=profile.regular_allowances if profile else Decimal("0"),
        payment_method=method, payment_detail=detail[:80],
    )
    recalc_line(line)
    return line


@transaction.atomic
def create_run(period, user):
    period = period.replace(day=1)
    if PayrollRun.objects.filter(period=period).exclude(status=S.REJECTED).exists():
        raise TransitionError(f"There is already a payroll for {period:%B %Y}.")
    try:
        with transaction.atomic():
            run = PayrollRun.objects.create(period=period, created_by=user, updated_by=user)
    except IntegrityError:
        raise TransitionError(f"There is already a payroll for {period:%B %Y}.")
    people = [u for u in payable_people() if not PayProfile.objects.filter(user=u, is_active=False).exists()]
    PayrollLine.objects.bulk_create([_line_for(run, u) for u in people])
    recalc_run(run)
    _log(user, "payroll.created", run, f"Started payroll for {period:%B %Y} with {len(people)} people")
    return run


def recalc_line(line):
    line.gross = sum((getattr(line, f) or Decimal("0") for f in EARNINGS), Decimal("0"))
    line.total_deductions = sum((getattr(line, f) or Decimal("0") for f in DEDUCTIONS), Decimal("0"))
    line.net = line.gross - line.total_deductions


def recalc_run(run):
    t = run.lines.aggregate(g=Sum("gross"), d=Sum("total_deductions"), n=Sum("net"))
    PayrollRun.objects.filter(pk=run.pk).update(
        total_gross=t["g"] or 0, total_deductions=t["d"] or 0, total_net=t["n"] or 0, updated_at=timezone.now()
    )
    run.refresh_from_db()


def _require_editable(run):
    if run.status not in EDITABLE:
        raise TransitionError("This payroll can't be changed now. It is " + run.get_status_display().lower() + ".")


@transaction.atomic
def save_line(line, user, before):
    run = PayrollRun.objects.select_for_update().get(pk=line.run_id)
    _require_editable(run)
    recalc_line(line)
    line.save()
    recalc_run(run)
    fields = list(EARNINGS + DEDUCTIONS) + ["other_note"]
    _log(user, "payroll.line_changed", run, f"Changed {line.employee_name}'s pay for {run.period:%B %Y}",
         audit.changes_between(before, audit.snapshot(line, fields)))
    PayrollRun.objects.filter(pk=run.pk).update(updated_by=user)


@transaction.atomic
def add_person(run, person, user):
    _require_editable(run)
    if person.role == Role.MANAGER or not person.is_active:
        raise TransitionError("Only active, non-Manager accounts can be added to payroll.")
    if run.lines.filter(employee=person).exists():
        raise TransitionError(f"{person} is already on this payroll.")
    _line_for(run, person).save()
    recalc_run(run)
    _log(user, "payroll.person_added", run, f"Added {person} to payroll {run.period:%B %Y}")


@transaction.atomic
def remove_line(line, user):
    run = line.run
    _require_editable(run)
    name = line.employee_name
    line.delete()
    recalc_run(run)
    _log(user, "payroll.person_removed", run, f"Removed {name} from payroll {run.period:%B %Y}")


def submit(run, user):
    if not run.lines.exists():
        raise TransitionError("The payroll has nobody on it.")
    negative = run.lines.filter(net__lt=0)
    if negative.exists():
        names = ", ".join(negative.values_list("employee_name", flat=True)[:5])
        raise TransitionError(f"Net pay is below zero for: {names}. Fix their deductions first.")
    if not advance(run, EDITABLE, S.SUBMITTED, submitted_by=user, submitted_at=timezone.now()):
        raise TransitionError("This payroll has already been submitted.")
    _log(user, "payroll.submitted", run, f"Submitted payroll {run.period:%B %Y} to the Manager (net KES {run.total_net:,.2f})")
    notify_role(Role.MANAGER, "payroll.submitted", f"Payroll for {run.period:%B %Y} needs your approval",
                f"{run.lines.count()} people, net pay KES {run.total_net:,.2f}.", link(run), Notification.Priority.HIGH, entity=run)


def manager_opened(run, user):
    """The first time a Manager opens a submitted payroll it becomes 'under review'."""
    if user.role == Role.MANAGER and advance(run, S.SUBMITTED, S.UNDER_REVIEW, reviewed_at=timezone.now()):
        _log(user, "payroll.under_review", run, f"Started reviewing payroll {run.period:%B %Y}")


def _decide(run, user, to_status, note, needs_note, verb, from_statuses=DECIDABLE):
    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager can do this.")
    if needs_note and not note.strip():
        raise TransitionError("Please write a short note explaining why.")
    extra = dict(decided_by=user, decided_at=timezone.now(), decision_note=note.strip())
    if to_status == S.REVISION_REQUIRED and run.status == S.APPROVED:
        extra = dict(reopened_by=user, reopened_at=timezone.now(), reopen_reason=note.strip(), decision_note=note.strip())
    if not advance(run, from_statuses, to_status, **extra):
        raise TransitionError("This payroll was already changed. Please refresh the page.")
    _log(user, f"payroll.{to_status}", run, f"{verb} payroll {run.period:%B %Y}" + (f": {note.strip()[:100]}" if note.strip() else ""))
    title = f"Payroll {run.period:%B %Y}: {run.get_status_display().lower()}"
    if run.submitted_by:
        notify(run.submitted_by, f"payroll.{to_status}", title, note.strip()[:200], link(run),
               Notification.Priority.HIGH, entity=run)
    else:
        notify_role(Role.SECRETARY, f"payroll.{to_status}", title, note.strip()[:200], link(run), entity=run)


def approve(run, user, note=""):
    _decide(run, user, S.APPROVED, note, False, "Approved")


def request_changes(run, user, note):
    _decide(run, user, S.REVISION_REQUIRED, note, True, "Sent back for changes")


def reject(run, user, note):
    _decide(run, user, S.REJECTED, note, True, "Rejected")


def reopen(run, user, note):
    _decide(run, user, S.REVISION_REQUIRED, note, True, "Reopened", from_statuses=(S.APPROVED,))


def exported(run, user, kind):
    _log(user, "payroll.exported", run, f"Exported payroll {run.period:%B %Y} as {kind}")
