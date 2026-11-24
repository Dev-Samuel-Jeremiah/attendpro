from django.conf import settings
from django.db import models


class Feature(models.Model):
    """A line on the pricing page. Built-in features (is_builtin) have a fixed `code` the app
    checks before unlocking a page or button; features the super admin adds are display-only
    until code is written for them."""
    STATUS_LIVE = "live"
    STATUS_SOON = "coming_soon"
    STATUS_CHOICES = [(STATUS_LIVE, "Available"), (STATUS_SOON, "Coming soon")]

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_LIVE)
    is_builtin = models.BooleanField(default=False, editable=False)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    @property
    def coming_soon(self):
        return self.status == self.STATUS_SOON


class Plan(models.Model):
    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=40, unique=True)
    tagline = models.CharField(max_length=160, blank=True)
    price = models.PositiveIntegerField(default=0, help_text="In naira. 0 means free.")
    period_days = models.PositiveIntegerField(default=30, help_text="How long one payment lasts, in days.")
    staff_limit = models.PositiveIntegerField(null=True, blank=True,
                                              help_text="Active accounts allowed, admins included. Blank = unlimited.")
    features = models.ManyToManyField(Feature, blank=True, related_name="plans")
    is_default = models.BooleanField(default=False,
                                     help_text="The free plan every organisation falls back to.")
    is_public = models.BooleanField(default=True, help_text="Shown on the pricing page.")
    highlight = models.BooleanField(default=False, help_text="Marked “Most popular” on the pricing page.")
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ["sort_order", "price"]

    def __str__(self):
        return self.name

    @property
    def is_free(self):
        return self.price == 0

    @property
    def period_label(self):
        return {30: "month", 31: "month", 90: "quarter", 365: "year", 366: "year"}.get(
            self.period_days, f"{self.period_days} days")

    def feature_codes(self):
        if not hasattr(self, "_codes"):
            self._codes = set(self.features.values_list("code", flat=True))
        return self._codes


class Payment(models.Model):
    STATUS_PENDING, STATUS_SUCCESS, STATUS_FAILED = "pending", "success", "failed"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_SUCCESS, "Paid"), (STATUS_FAILED, "Failed")]

    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="payments")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="payments")
    amount_kobo = models.PositiveBigIntegerField()
    reference = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    channel = models.CharField(max_length=30, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.reference

    @property
    def amount(self):
        return self.amount_kobo // 100


class SiteSettings(models.Model):
    """Public contact details shown on the website (one row, edited in Platform → Site settings)."""
    company_name = models.CharField(max_length=120, default="Techmiary Technology Concepts")
    contact_email = models.EmailField("Support email", blank=True)
    sales_email = models.EmailField("Sales email", blank=True)
    phone = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField("WhatsApp number", max_length=30, blank=True,
                                help_text="International format, e.g. +234 803 000 0000")
    address = models.CharField(max_length=255, blank=True)
    hours = models.CharField("Support hours", max_length=120, blank=True, help_text="e.g. Mon–Fri, 8am–6pm WAT")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "site settings"

    @classmethod
    def load(cls):
        return cls.objects.first() or cls.objects.create()

    @property
    def whatsapp_digits(self):
        return "".join(ch for ch in self.whatsapp if ch.isdigit())

    @property
    def has_contact(self):
        return any([self.contact_email, self.sales_email, self.phone, self.whatsapp, self.address])


class Testimonial(models.Model):
    """A real customer quote. Only published ones appear on the website."""
    quote = models.TextField(max_length=400)
    name = models.CharField(max_length=80)
    role = models.CharField(max_length=80, blank=True, help_text="e.g. Principal")
    organisation = models.CharField(max_length=120)
    logo = models.ImageField(upload_to="logos/site/", blank=True, null=True)
    is_published = models.BooleanField("Show on the website", default=False,
                                       help_text="Only publish quotes you have permission to use.")
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.name}, {self.organisation}"


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    organisation = models.CharField(max_length=160, blank=True)
    staff_count = models.CharField("Number of staff", max_length=20, blank=True)
    message = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField(default=False)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
