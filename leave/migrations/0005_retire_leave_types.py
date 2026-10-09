"""Frank's rule: leave is Annual, Maternity, Paternity or Compassionate. Sick is reported, not asked for.

The other types are switched off, never deleted, so old requests keep their type. Reversible.
"""
from django.db import migrations

RETIRED = ("pre_adoptive", "unpaid", "sick")


def retire(apps, schema_editor):
    apps.get_model("leave", "LeaveType").objects.filter(code__in=RETIRED).update(is_active=False)


def restore(apps, schema_editor):
    apps.get_model("leave", "LeaveType").objects.filter(code__in=RETIRED).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [("leave", "0004_leave_days_given")]
    operations = [migrations.RunPython(retire, restore)]
