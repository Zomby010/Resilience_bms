from django.db import migrations

DEFAULT_CATEGORIES = [
    "Uniforms",
    "Protective Equipment",
    "Electronics",
    "Office Equipment",
    "Stationery",
    "Tools",
    "Security Equipment",
    "Other",
]


def add_categories(apps, schema_editor):
    Category = apps.get_model("inventory", "Category")
    for name in DEFAULT_CATEGORIES:
        Category.objects.get_or_create(name=name)


def remove_unused_categories(apps, schema_editor):
    # Only removes starting categories that no item uses, so no data is lost on rollback.
    Category = apps.get_model("inventory", "Category")
    Category.objects.filter(name__in=DEFAULT_CATEGORIES, items__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [migrations.RunPython(add_categories, remove_unused_categories)]
