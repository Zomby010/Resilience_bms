from django.db import migrations

# Kenyan Employment Act 2007 minimums: annual 21 working days (s.28), sick 7 full + 7 half pay (s.30),
# maternity 3 months (s.29), paternity 2 weeks (s.29(8)), pre-adoptive 1 month (s.29A, 2021 amendment).
TYPES = [
    ("annual", "Annual leave", 21, "working", True, 1),
    ("sick", "Sick leave", 14, "calendar", False, 2),
    ("maternity", "Maternity leave", 90, "calendar", True, 3),
    ("paternity", "Paternity leave", 14, "calendar", True, 4),
    ("pre_adoptive", "Pre-adoptive leave", 30, "calendar", True, 5),
    ("compassionate", "Compassionate leave", 5, "working", True, 6),
    ("unpaid", "Unpaid leave", 0, "working", False, 7),
]


def seed(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    for code, name, days, counting, needs_balance, order in TYPES:
        LeaveType.objects.get_or_create(code=code, defaults={
            "name": name, "days_per_year": days, "counting": counting, "needs_balance": needs_balance, "order": order,
        })


class Migration(migrations.Migration):
    dependencies = [("leave", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
