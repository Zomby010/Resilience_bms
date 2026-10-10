from django.db import migrations, models

COLOURS = ["blue", "orange", "green", "purple", "sky", "red", "yellow", "black"]


def give_colours(apps, schema_editor):
    Site = apps.get_model("tracking", "Site")
    for i, site in enumerate(Site.objects.filter(colour="").order_by("pk")):
        site.colour = COLOURS[i % len(COLOURS)]
        site.save(update_fields=["colour"])


class Migration(migrations.Migration):
    dependencies = [("tracking", "0002_site_address_site_details_updated_at_and_more")]

    operations = [
        migrations.AddField(
            model_name="site",
            name="colour",
            field=models.CharField(
                blank=True, max_length=10,
                choices=[("blue", "Blue"), ("orange", "Orange"), ("green", "Green"), ("purple", "Pink-purple"),
                         ("sky", "Sky blue"), ("red", "Red-orange"), ("yellow", "Yellow"), ("black", "Black")],
                help_text="Shown as a stripe on this site's OB entries, always with its name. Picked automatically; change it if two sites look alike.",
            ),
        ),
        migrations.RunPython(give_colours, migrations.RunPython.noop),
    ]
