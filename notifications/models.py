from django.conf import settings
from django.db import models


class Notification(models.Model):
    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="notifications")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30, default="info")
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return self.title


class AlertLog(models.Model):
    """Remembers which scheduled alerts already went out, so each is sent once."""
    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="alert_logs")
    date = models.DateField()
    kind = models.CharField(max_length=30)

    class Meta:
        unique_together = ("organisation", "date", "kind")
