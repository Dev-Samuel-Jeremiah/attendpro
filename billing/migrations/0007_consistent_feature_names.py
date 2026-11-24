"""One consistent story about GPS on every page, and CSV export named on the plans.
Only renames features the super admin hasn't already renamed."""
from django.db import migrations

RENAMES = {
    "manual_clock": (("Clock-in button with location check",), "GPS clock-in button",
                     "Staff clock in from their phone; GPS confirms they're at your premises"),
    "geofencing": (("GPS and geofencing",), "GPS on QR scans and branch geofences",
                   "QR scans are GPS-checked too, and every branch has its own boundary"),
    "exports": (("Excel and PDF export",), "Excel, CSV and PDF export", "Download reports as Excel, CSV or PDF"),
}


def rename(apps, schema_editor):
    Feature = apps.get_model("billing", "Feature")
    for code, (old_names, name, desc) in RENAMES.items():
        Feature.objects.filter(code=code, name__in=old_names).update(name=name, description=desc)


class Migration(migrations.Migration):
    dependencies = [("billing", "0006_site_contact")]
    operations = [migrations.RunPython(rename, migrations.RunPython.noop)]
