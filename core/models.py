import secrets
from datetime import datetime, time, timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


def _kiosk_key():
    return secrets.token_urlsafe(18)


class Organisation(models.Model):
    TYPE_CHOICES = [("company", "Company / Organisation"), ("school", "School / Institution")]
    WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    name = models.CharField(max_length=160)
    code = models.CharField(
        max_length=8, unique=True,
        help_text="Short prefix used for member IDs, e.g. TMY → TMY-0001",
    )
    org_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="company")
    address = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)

    # Attendance rules
    work_start = models.TimeField(default=time(8, 0))
    work_end = models.TimeField(default=time(16, 0))
    grace_minutes = models.PositiveIntegerField(default=10, help_text="Minutes after start before an arrival counts as late")
    working_days = models.CharField(max_length=20, default="0,1,2,3,4", help_text="Weekday numbers, Monday=0")
    checkout_gap_minutes = models.PositiveIntegerField(
        default=5, help_text="Scans closer together than this are treated as duplicates")

    # Reception QR
    kiosk_key = models.CharField(max_length=40, unique=True, default=_kiosk_key)
    qr_rotation_seconds = models.PositiveIntegerField(default=30)

    # Where members may use the clock-in button
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_radius_m = models.PositiveIntegerField(
        "Allowed distance (metres)", default=100,
        help_text="How far from the set location members can be and still clock in")

    # Subscription. No plan, or an expired paid plan, means the free default plan.
    plan = models.ForeignKey("billing.Plan", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="organisations")
    plan_expires_at = models.DateTimeField(null=True, blank=True,
                                           help_text="Blank = does not expire")

    # Automated notifications (Professional and up)
    notify_late = models.BooleanField("Tell admins about late arrivals", default=True)
    notify_absent = models.BooleanField("Daily alert about people who haven't clocked in", default=True)
    notify_checkout = models.BooleanField("Remind people who forget to clock out", default=True)
    email_notifications = models.BooleanField("Also send notifications by email", default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    # ---- Plan & limits ---------------------------------------------------- #
    @property
    def plan_is_expired(self):
        return bool(self.plan_id and self.plan_expires_at and self.plan_expires_at <= timezone.now())

    @property
    def current_plan(self):
        """The plan in force right now (cached on this instance for the request)."""
        if not hasattr(self, "_current_plan"):
            from billing.models import Plan
            plan = self.plan
            if plan is None or self.plan_is_expired:
                plan = Plan.objects.filter(is_default=True).first()
            self._current_plan = plan
        return self._current_plan

    def forget_plan(self):
        self.__dict__.pop("_current_plan", None)

    def has_feature(self, code):
        plan = self.current_plan
        return bool(plan and code in plan.feature_codes())

    @property
    def staff_limit(self):
        plan = self.current_plan
        return plan.staff_limit if plan else None

    def active_member_count(self):
        return self.members.filter(is_active=True).count()

    def seats_left(self):
        """None when unlimited."""
        if self.staff_limit is None:
            return None
        return max(self.staff_limit - self.active_member_count(), 0)

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def is_school(self):
        return self.org_type == "school"

    @property
    def member_label(self):
        return "Member" if not self.is_school else "Staff / Student"

    def working_day_list(self):
        return [int(d) for d in self.working_days.split(",") if d.strip().isdigit()]

    def working_day_names(self):
        return [self.WEEKDAYS[d] for d in self.working_day_list()]

    def is_working_day(self, d):
        return d.weekday() in self.working_day_list()

    def late_cutoff(self, d):
        start = datetime.combine(d, self.work_start)
        return (start + timedelta(minutes=self.grace_minutes)).time()

    def next_member_id(self):
        prefix = f"{self.code}-"
        last = (User.objects.filter(organisation=self, username__startswith=prefix)
                .order_by("-username").values_list("username", flat=True).first())
        n = 1
        if last:
            try:
                n = int(last.split("-")[-1]) + 1
            except ValueError:
                n = User.objects.filter(organisation=self).count() + 1
        return f"{prefix}{n:04d}"

    def rotate_kiosk_key(self):
        self.kiosk_key = _kiosk_key()
        self.save(update_fields=["kiosk_key"])


class Branch(models.Model):
    """A site of a multi-branch organisation (Enterprise): own location, radius and reception QR."""
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_m = models.PositiveIntegerField("Allowed distance (metres)", default=100)
    kiosk_key = models.CharField(max_length=40, unique=True, default=_kiosk_key)
    is_active = models.BooleanField("Active", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("organisation", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    def rotate_kiosk_key(self):
        self.kiosk_key = _kiosk_key()
        self.save(update_fields=["kiosk_key"])


class Department(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = ("organisation", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    """`username` holds the member ID (e.g. TMY-0007) used to sign in."""
    ROLE_ADMIN = "admin"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [(ROLE_ADMIN, "Administrator"), (ROLE_MEMBER, "Staff / Student")]
    CATEGORY_CHOICES = [("staff", "Staff"), ("student", "Student")]

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, null=True, blank=True,
                                     related_name="members")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default="staff")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="members")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="members",
                               help_text="Where this person normally works")
    designation = models.CharField(max_length=100, blank=True, help_text="Job title or class")
    phone = models.CharField(max_length=30, blank=True)
    photo = models.ImageField(upload_to="photos/", blank=True, null=True)

    class Meta:
        ordering = ["first_name", "last_name"]

    @property
    def is_org_admin(self):
        return self.role == self.ROLE_ADMIN

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = [p for p in [self.first_name, self.last_name] if p]
        return "".join(p[0] for p in parts).upper() or self.username[:2].upper()


class AttendanceRecord(models.Model):
    STATUS_PRESENT = "present"
    STATUS_LATE = "late"
    STATUS_LEAVE = "leave"
    STATUS_ABSENT = "absent"
    STATUS_CHOICES = [
        (STATUS_PRESENT, "On time"),
        (STATUS_LATE, "Late"),
        (STATUS_LEAVE, "On leave / excused"),
        (STATUS_ABSENT, "Absent"),
    ]
    SOURCE_CHOICES = [("qr", "QR scan"), ("location", "Clock-in button"), ("manual", "Manual entry"),
                      ("leave", "Approved leave")]

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="attendance")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField(db_index=True)
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PRESENT)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="qr")
    note = models.CharField(max_length=255, blank=True)
    check_in_ip = models.GenericIPAddressField(null=True, blank=True)
    check_out_ip = models.GenericIPAddressField(null=True, blank=True)
    leave_request = models.ForeignKey("leave.LeaveRequest", on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="records")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="attendance",
                               help_text="Where they checked in")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "date")
        ordering = ["-date", "check_in"]

    def __str__(self):
        return f"{self.user.username} {self.date}"

    @property
    def worked(self):
        if self.check_in and self.check_out and self.check_out > self.check_in:
            return self.check_out - self.check_in
        return None

    @property
    def worked_hours(self):
        w = self.worked
        return round(w.total_seconds() / 3600, 2) if w else 0

    @property
    def worked_display(self):
        w = self.worked
        if not w:
            return "—"
        mins = int(w.total_seconds() // 60)
        return f"{mins // 60}h {mins % 60:02d}m"

    @property
    def late_by_minutes(self):
        if self.status != self.STATUS_LATE or not self.check_in:
            return 0
        local_in = timezone.localtime(self.check_in)
        start = timezone.make_aware(datetime.combine(self.date, self.organisation.work_start),
                                    local_in.tzinfo)
        return max(0, int((local_in - start).total_seconds() // 60))


class ScanLog(models.Model):
    """Every scan attempt, accepted or not — the audit trail."""
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="scan_logs")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scan_logs")
    timestamp = models.DateTimeField(default=timezone.now)
    action = models.CharField(max_length=20)  # check_in / check_out / duplicate / rejected
    message = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    # Filled in for the clock-in button
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    distance_m = models.PositiveIntegerField(null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="scan_logs")

    class Meta:
        ordering = ["-timestamp"]


class SavedReport(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="reports")
    title = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    file = models.FileField(upload_to="reports/")
    file_format = models.CharField(max_length=10)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
