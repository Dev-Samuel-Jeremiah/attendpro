from django.conf import settings
from django.db import models


class LeaveType(models.Model):
    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="leave_types")
    name = models.CharField(max_length=60)
    days_per_year = models.PositiveIntegerField(null=True, blank=True,
                                                help_text="Working days each person gets per year. Blank = no limit.")
    is_paid = models.BooleanField("Paid leave", default=True)
    is_active = models.BooleanField("Can be requested", default=True)

    class Meta:
        unique_together = ("organisation", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    PENDING, APPROVED, REJECTED, CANCELLED = "pending", "approved", "rejected", "cancelled"
    STATUS_CHOICES = [(PENDING, "Pending"), (APPROVED, "Approved"), (REJECTED, "Declined"), (CANCELLED, "Cancelled")]

    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="leave_requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    start_date = models.DateField()
    end_date = models.DateField()
    days = models.PositiveIntegerField(help_text="Working days in the range")
    reason = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} {self.leave_type} {self.start_date}–{self.end_date}"

    @property
    def is_open(self):
        return self.status in (self.PENDING, self.APPROVED)
