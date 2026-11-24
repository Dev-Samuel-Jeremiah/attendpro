from decimal import Decimal

from django.conf import settings
from django.db import models


class PaySettings(models.Model):
    """How attendance turns into pay deductions, for one organisation."""
    ABSENCE_DAILY, ABSENCE_FIXED, ABSENCE_NONE = "daily_rate", "fixed", "none"
    ABSENCE_CHOICES = [(ABSENCE_DAILY, "Deduct a day's pay (salary ÷ working days in the month)"),
                       (ABSENCE_FIXED, "Deduct a fixed amount per day"), (ABSENCE_NONE, "Don't deduct")]

    organisation = models.OneToOneField("core.Organisation", on_delete=models.CASCADE, related_name="pay_settings")
    late_fee = models.PositiveIntegerField("Deduction per late arrival (₦)", default=0)
    free_lates = models.PositiveIntegerField("Late arrivals allowed each month before deducting", default=0)
    absence_mode = models.CharField("Absences (monthly salaries)", max_length=12, choices=ABSENCE_CHOICES,
                                    default=ABSENCE_DAILY)
    absence_fee = models.PositiveIntegerField("Fixed deduction per absent day (₦)", default=0)
    deduct_unpaid_leave = models.BooleanField("Treat unpaid leave like an absence", default=True)


class PayProfile(models.Model):
    MONTHLY, DAILY, HOURLY = "monthly", "daily", "hourly"
    TYPE_CHOICES = [(MONTHLY, "Monthly salary"), (DAILY, "Daily rate"), (HOURLY, "Hourly rate")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pay")
    pay_type = models.CharField(max_length=8, choices=TYPE_CHOICES, default=MONTHLY)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    bank_name = models.CharField(max_length=80, blank=True)
    account_number = models.CharField(max_length=20, blank=True)
    account_name = models.CharField(max_length=120, blank=True)


class PayrollRun(models.Model):
    DRAFT, FINAL = "draft", "final"
    STATUS_CHOICES = [(DRAFT, "Draft"), (FINAL, "Finalised")]

    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="payroll_runs")
    month = models.DateField(help_text="First day of the month")
    status = models.CharField(max_length=6, choices=STATUS_CHOICES, default=DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    finalised_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("organisation", "month")
        ordering = ["-month"]

    def __str__(self):
        return f"{self.month:%B %Y}"

    @property
    def is_final(self):
        return self.status == self.FINAL


class PayrollLine(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payslips")
    pay_type = models.CharField(max_length=8, choices=PayProfile.TYPE_CHOICES)
    rate = models.DecimalField(max_digits=12, decimal_places=2)
    working_days = models.PositiveIntegerField(default=0)  # in the whole month
    expected = models.PositiveIntegerField(default=0)
    attended = models.PositiveIntegerField(default=0)
    late = models.PositiveIntegerField(default=0)
    absent = models.PositiveIntegerField(default=0)
    paid_leave = models.PositiveIntegerField(default=0)
    unpaid_leave = models.PositiveIntegerField(default=0)
    hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0"))
    gross = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    late_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    absence_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    adjustment = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"),
                                     help_text="Bonus (positive) or other deduction (negative)")
    adjustment_note = models.CharField(max_length=120, blank=True)
    net = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        unique_together = ("run", "user")
        ordering = ["user__first_name", "user__last_name"]

    @property
    def deductions(self):
        return self.late_deduction + self.absence_deduction
