from django.core.management.base import BaseCommand

from notifications.services import run_scheduled_alerts


class Command(BaseCommand):
    help = "Send due absence, clock-out and plan-expiry alerts. Run every few minutes (attendpro-alerts.timer)."

    def handle(self, *args, **opts):
        for code, kind, n in run_scheduled_alerts():
            self.stdout.write(f"{code}: {kind} → {n}")
