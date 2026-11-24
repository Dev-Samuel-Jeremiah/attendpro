from django.conf import settings
from django.db import models

from core.storage import private_storage


class OrgBackup(models.Model):
    """A ZIP of everything an organisation has in AttendPro (CSV files). Kept privately on the server."""
    AUTO, MANUAL = "auto", "manual"
    KIND_CHOICES = [(AUTO, "Weekly automatic"), (MANUAL, "Made by hand")]

    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="backups")
    kind = models.CharField(max_length=6, choices=KIND_CHOICES, default=AUTO)
    file = models.FileField(storage=private_storage, upload_to="org-backups/")
    size = models.PositiveBigIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class DeletedItem(models.Model):
    """Something an administrator deleted, kept for 30 days so it can be put back."""
    ATTENDANCE, DEPARTMENT, BRANCH = "attendance", "department", "branch"
    KIND_CHOICES = [(ATTENDANCE, "Attendance entry"), (DEPARTMENT, "Department"), (BRANCH, "Branch")]

    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="deleted_items")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    label = models.CharField(max_length=200)
    payload = models.JSONField()
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    deleted_at = models.DateTimeField(auto_now_add=True)
    restored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-deleted_at"]
