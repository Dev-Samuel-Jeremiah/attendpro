"""Describe QR attendance without promising a refreshing code (refresh can be switched off).
Only changes the description if the super admin hasn't already edited it."""
from django.db import migrations

OLD = "Rotating QR code on a reception screen"
NEW = "Staff scan a QR code at your reception or entrance"


def update(apps, schema_editor):
    apps.get_model("billing", "Feature").objects.filter(code="qr_attendance", description=OLD).update(description=NEW)


def revert(apps, schema_editor):
    apps.get_model("billing", "Feature").objects.filter(code="qr_attendance", description=NEW).update(description=OLD)


class Migration(migrations.Migration):
    dependencies = [("billing", "0008_yearly_billing")]
    operations = [migrations.RunPython(update, revert)]
