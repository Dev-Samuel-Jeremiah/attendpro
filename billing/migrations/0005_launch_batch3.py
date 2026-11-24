"""Face verification, payroll and advanced backup & recovery are built: mark them available."""
from django.db import migrations

LAUNCH = ["face_verification", "payroll", "advanced_backup"]
DESCRIPTIONS = {
    "face_verification": ("Selfie check at clock-in", "A selfie at check-in, matched to the person's face on our server"),
    "payroll": ("Hours and lateness feed into payroll",
                "Monthly payroll from attendance: deductions, payslips and a bank transfer file"),
    "advanced_backup": ("", "Weekly backups you can download, and 30 days to restore deleted entries"),
}


def launch(apps, schema_editor):
    Feature = apps.get_model("billing", "Feature")
    Feature.objects.filter(code__in=LAUNCH, status="coming_soon").update(status="live")
    for code, (old, new) in DESCRIPTIONS.items():
        Feature.objects.filter(code=code, description=old).update(description=new)


def unlaunch(apps, schema_editor):
    apps.get_model("billing", "Feature").objects.filter(code__in=LAUNCH).update(status="coming_soon")


class Migration(migrations.Migration):
    dependencies = [("billing", "0004_launch_batch2")]
    operations = [migrations.RunPython(launch, unlaunch)]
