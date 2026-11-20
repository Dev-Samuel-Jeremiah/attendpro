"""Leave management, automated notifications and PDF export are built: mark them available.
Only touches features the super admin hasn't already changed."""
from django.db import migrations

LAUNCH = ["leave_management", "notifications"]
OLD_EXPORT_DESC = "Excel and CSV downloads now; PDF coming soon"


def launch(apps, schema_editor):
    Feature = apps.get_model("billing", "Feature")
    Feature.objects.filter(code__in=LAUNCH, status="coming_soon").update(status="live")
    Feature.objects.filter(code="exports", description=OLD_EXPORT_DESC).update(
        description="Download reports as Excel, CSV or PDF")
    Feature.objects.filter(code="notifications", description="Late and absence alerts").update(
        description="In-app and email alerts: late arrivals, absences, missed clock-outs, leave decisions")


def unlaunch(apps, schema_editor):
    Feature = apps.get_model("billing", "Feature")
    Feature.objects.filter(code__in=LAUNCH).update(status="coming_soon")


class Migration(migrations.Migration):
    dependencies = [("billing", "0002_seed_plans")]
    operations = [migrations.RunPython(launch, unlaunch)]
