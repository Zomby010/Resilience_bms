"""Who may see a record that a file or notification points to.

One place answers "may this user see this record?", so file downloads use exactly the same
rules as the pages that show the record.
"""
from accounts.models import Role


def can_view(user, obj):
    if obj is None or not user.is_authenticated:
        return False
    label = obj._meta.label_lower
    office = user.role in (Role.SECRETARY, Role.MANAGER)
    if label in ("clients.issue",):
        return office or (user.role == Role.SUPERVISOR and obj.supervisor_id == user.pk)
    if label in ("clients.client", "clients.message", "clients.feedback", "billing.invoice", "inventory.item"):
        return office
    if label == "finance.expense":
        return office
    if label == "escalations.escalation":
        return office
    if label == "inventory.itemrequest":
        return office or obj.requester_id == user.pk
    if label in ("payroll.payrollrun",):
        return office
    if label == "incidents.incident":
        return type(obj).objects.visible_to(user).filter(pk=obj.pk).exists()
    if label == "operations.sitevisit":
        return office or obj.supervisor_id == user.pk
    if label == "payroll.payrollline":  # a payslip: the office, or the person it belongs to once approved
        return office or (obj.employee_id == user.pk and obj.run.status == "approved")
    return False
