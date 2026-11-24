from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from faces.services import purge_old_checks
from notifications.services import run_scheduled_alerts
from recovery.services import purge_deleted, weekly_backups


class Command(BaseCommand):
    help = ("Send due absence, clock-out and plan-expiry alerts, make weekly organisation backups and clear "
            "expired data. Run every few minutes (attendpro-alerts.timer).")

    def handle(self, *args, **opts):
        for code, kind, n in run_scheduled_alerts():
            self.stdout.write(f"{code}: {kind} → {n}")
        for code in weekly_backups():
            self.stdout.write(f"{code}: weekly backup made")
        purge_deleted()
        purge_old_checks(timezone.now() - timedelta(days=90))
