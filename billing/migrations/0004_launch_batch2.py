"""Multiple branches, GPS & geofencing and advanced analytics are built: mark them available."""
from django.db import migrations

LAUNCH = ["multi_branch", "geofencing", "advanced_analytics"]
DESCRIPTIONS = {
    "multi_branch": ("", "Each branch with its own location, reception QR screen and staff"),
    "geofencing": ("Location check on every scan, several sites",
                   "GPS check on QR scans too; staff can clock in at any branch"),
    "advanced_analytics": ("Trends and patterns across your organisation",
                           "Trends, weekday patterns, arrival times and team comparisons"),
}


def launch(apps, schema_editor):
    Feature = apps.get_model("billing", "Feature")
    Feature.objects.filter(code__in=LAUNCH, status="coming_soon").update(status="live")
    for code, (old, new) in DESCRIPTIONS.items():
        Feature.objects.filter(code=code, description=old).update(description=new)


def unlaunch(apps, schema_editor):
    apps.get_model("billing", "Feature").objects.filter(code__in=LAUNCH).update(status="coming_soon")


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_launch_batch1")]
    operations = [migrations.RunPython(launch, unlaunch)]
