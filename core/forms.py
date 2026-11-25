from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password

from billing.models import Plan

from .models import AttendanceRecord, Branch, Department, Organisation, User


class StyledMixin:
    def _style(self):
        for f in self.fields.values():
            w = f.widget
            if isinstance(w, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
                continue
            w.attrs.setdefault("class", "input")


class LoginForm(StyledMixin, forms.Form):
    username = forms.CharField(label="ID", widget=forms.TextInput(attrs={
        "placeholder": "e.g. TMY-0001", "autocomplete": "username", "autocapitalize": "characters"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        "placeholder": "Password", "autocomplete": "current-password"}))
    remember = forms.BooleanField(label="Keep me signed in on this device", required=False, initial=True)

    def __init__(self, request=None, *a, **kw):
        self.request = request
        self.user = None
        super().__init__(*a, **kw)
        self._style()

    def clean(self):
        cd = super().clean()
        u, p = cd.get("username", "").strip(), cd.get("password")
        if u and p:
            # IDs aren't case-sensitive ("tmy-0001" = "TMY-0001"; "PLATFORMADMIN" = "platformadmin")
            match = User.objects.filter(username__iexact=u).values_list("username", flat=True).first()
            user = authenticate(self.request, username=match or u, password=p)
            if user is None:
                raise forms.ValidationError("Incorrect ID or password.")
            if not user.is_active:
                raise forms.ValidationError("This account has been deactivated. Contact your administrator.")
            self.user = user
        return cd


_CODE_SKIP = {"and", "of", "the", "for", "&", "ltd", "limited", "plc", "inc", "nig", "nigeria"}


def suggest_code(name: str) -> str:
    """A short ID prefix from an organisation name: "Techmiary Technology Concepts" → "TTC".
    Adds a number if that's taken."""
    words = [w for w in "".join(ch if ch.isalnum() else " " for ch in (name or "")).split() if w.lower() not in _CODE_SKIP]
    if not words:
        return ""
    base = "".join(w[0] for w in words).upper()[:6] if len(words) > 1 else words[0][:4].upper()
    if len(base) < 2:
        base = (words[0][:3]).upper()
    if len(base) < 2:
        return ""
    code, n = base, 2
    while Organisation.objects.filter(code=code).exists():
        code = f"{base[:5]}{n}"[:6]
        n += 1
    return code


class OrgRegisterForm(StyledMixin, forms.Form):
    plan = forms.ModelChoiceField(queryset=Plan.objects.none(), widget=forms.RadioSelect, empty_label=None,
                                  error_messages={"required": "Choose a plan to continue.",
                                                  "invalid_choice": "Choose one of the plans shown."})
    org_name = forms.CharField(label="Organisation name", max_length=160)
    org_type = forms.ChoiceField(label="Type", choices=Organisation.TYPE_CHOICES)
    code = forms.CharField(label="Short code", max_length=6, min_length=2,
                           help_text="2–6 letters used as the ID prefix, e.g. TMY")
    first_name = forms.CharField(label="Your first name", max_length=60)
    last_name = forms.CharField(label="Your last name", max_length=60)
    email = forms.EmailField(label="Your email")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["plan"].queryset = Plan.objects.filter(is_public=True).order_by("sort_order", "price")
        hints = {"org_name": ("organization", "e.g. Techmiary Technology Concepts"), "code": ("off", "e.g. TTC"),
                 "first_name": ("given-name", ""), "last_name": ("family-name", ""), "email": ("email", "you@example.com"),
                 "password1": ("new-password", "At least 6 characters"), "password2": ("new-password", "Type it again")}
        for name, (auto, placeholder) in hints.items():
            self.fields[name].widget.attrs.update({"autocomplete": auto, "placeholder": placeholder})
        self.fields["code"].widget.attrs.update({"maxlength": 6, "autocapitalize": "characters", "spellcheck": "false"})
        self._style()

    # Frequent slips in email domains: catch them before the welcome email goes nowhere.
    EMAIL_TYPOS = {"gmial.com": "gmail.com", "gmai.com": "gmail.com", "gamil.com": "gmail.com", "gmail.co": "gmail.com",
                   "gmail.con": "gmail.com", "gmail.cm": "gmail.com", "gnail.com": "gmail.com", "gmaill.com": "gmail.com",
                   "yaho.com": "yahoo.com", "yahoo.con": "yahoo.com", "yahooo.com": "yahoo.com", "hotmial.com": "hotmail.com",
                   "hotmail.con": "hotmail.com", "outlook.con": "outlook.com", "outlok.com": "outlook.com",
                   "iclod.com": "icloud.com", "icloud.con": "icloud.com"}

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        local, _, domain = email.rpartition("@")
        fix = self.EMAIL_TYPOS.get(domain.lower())
        if fix:
            raise forms.ValidationError(f"Did you mean {local}@{fix}? Please check your email address.")
        return email

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if not code.isalnum():
            raise forms.ValidationError("Use letters and numbers only.")
        if Organisation.objects.filter(code=code).exists():
            alt = suggest_code(code)
            raise forms.ValidationError(f"{code} is already taken." + (f" Try {alt}." if alt else ""))
        return code

    def clean(self):
        cd = super().clean()
        if cd.get("password1") != cd.get("password2"):
            self.add_error("password2", "Passwords do not match.")
        elif cd.get("password1"):
            try:
                validate_password(cd["password1"])
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cd


class MemberForm(StyledMixin, forms.ModelForm):
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False),
                               help_text="Leave blank to keep the current password (or auto-generate for new members).")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "category", "department", "branch", "designation", "email", "phone",
                  "photo", "role", "is_active"]
        labels = {"designation": "Job title / class", "role": "Access level", "is_active": "Active"}

    def __init__(self, org, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["department"].queryset = Department.objects.filter(organisation=org)
        from billing import catalog
        if org.has_feature(catalog.MULTI_BRANCH):
            self.fields["branch"].queryset = org.branches.filter(is_active=True)
            self.fields["branch"].empty_label = "Main location"
        else:
            del self.fields["branch"]
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self._style()


class DepartmentForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._style()


class ImportForm(forms.Form):
    file = forms.FileField(help_text="CSV with columns: first_name, last_name, category, department, "
                                     "designation, email, phone")


class OrgSettingsForm(StyledMixin, forms.ModelForm):
    working_days_choice = forms.MultipleChoiceField(
        label="Working days", widget=forms.CheckboxSelectMultiple,
        choices=[(str(i), d) for i, d in enumerate(Organisation.WEEKDAYS)])

    class Meta:
        model = Organisation
        fields = ["name", "org_type", "address", "email", "phone", "logo", "work_start", "work_end",
                  "grace_minutes", "checkout_gap_minutes", "qr_rotation_seconds", "qr_rotate",
                  "latitude", "longitude", "location_radius_m",
                  "notify_late", "notify_absent", "notify_checkout", "email_notifications",
                  "face_required", "face_auto_enrol", "attendance_method"]
        widgets = {
            "work_start": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "work_end": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }
        labels = {
            "grace_minutes": "Grace period (minutes)",
            "checkout_gap_minutes": "Minimum gap between scans (minutes)",
            "qr_rotation_seconds": "QR refresh interval (seconds)",
        }
        help_texts = {
            "work_end": "Check-in closes at this time until the next day. Members already in can still check out.",
        }

    def __init__(self, *a, branding=True, notifications=True, face=True, method_choice=True, **kw):
        super().__init__(*a, **kw)
        if not method_choice:
            del self.fields["attendance_method"]
        else:
            self.fields["attendance_method"].widget = forms.RadioSelect(choices=Organisation.METHOD_CHOICES)
        if not face:
            del self.fields["face_required"], self.fields["face_auto_enrol"]
        if not branding:
            del self.fields["logo"]  # custom branding is a plan feature
        if not notifications:
            for f in ("notify_late", "notify_absent", "notify_checkout", "email_notifications"):
                del self.fields[f]
        self.fields["working_days_choice"].initial = [str(d) for d in self.instance.working_day_list()]
        self.fields["qr_rotation_seconds"].min_value = 10
        self.fields["qr_rotate"].widget.attrs.update({"class": "switch", "role": "switch"})
        self.fields["location_radius_m"].min_value = 20
        self.fields["location_radius_m"].max_value = 5000
        for f in ("latitude", "longitude"):
            self.fields[f].widget.attrs.update({"step": "any", "inputmode": "decimal"})
        self._style()

    def clean(self):
        cd = super().clean()
        lat, lng = cd.get("latitude"), cd.get("longitude")
        if (lat is None) != (lng is None):
            raise forms.ValidationError("Set both latitude and longitude, or clear both.")
        if lat is not None and not (-90 <= lat <= 90):
            self.add_error("latitude", "Latitude must be between -90 and 90.")
        if lng is not None and not (-180 <= lng <= 180):
            self.add_error("longitude", "Longitude must be between -180 and 180.")
        return cd

    def save(self, commit=True):
        self.instance.working_days = ",".join(sorted(self.cleaned_data["working_days_choice"]))
        return super().save(commit)


class RecordForm(StyledMixin, forms.ModelForm):
    """An administrator's entry for a day with no scan: on leave/excused or absent, never clock times."""
    STATUS_CHOICES = [(AttendanceRecord.STATUS_LEAVE, "On leave / excused"),
                      (AttendanceRecord.STATUS_ABSENT, "Absent")]

    class Meta:
        model = AttendanceRecord
        fields = ["user", "date", "status", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, org, *a, **kw):
        super().__init__(*a, **kw)
        self.org = org
        self.fields["user"].queryset = org.members.filter(is_active=True)
        self.fields["user"].label = "Member"
        self.fields["status"].choices = self.STATUS_CHOICES
        if self.instance.pk:  # an existing entry stays on its person and day
            for f in ("user", "date"):
                self.fields[f].disabled = True
        self._style()

    def clean(self):
        cd = super().clean()
        if self.instance.pk and self.instance.is_locked:
            raise forms.ValidationError("Scanned attendance can't be changed.")
        user, d = cd.get("user"), cd.get("date")
        if user and d:
            qs = AttendanceRecord.objects.filter(user=user, date=d)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(f"{user.display_name} already has attendance for that day. "
                                            "Scanned attendance can't be changed.")
        return cd

    def save(self, commit=True):
        rec = super().save(commit=False)
        rec.organisation = self.org
        rec.source = "manual"
        rec.check_in = rec.check_out = None
        if commit:
            rec.save()
        return rec


class RecordCommentForm(StyledMixin, forms.ModelForm):
    """The only thing an administrator can add to a scanned record."""
    class Meta:
        model = AttendanceRecord
        fields = ["note"]
        labels = {"note": "Administrator's comment"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._style()


class ChangePasswordForm(StyledMixin, forms.Form):
    current = forms.CharField(label="Current password", widget=forms.PasswordInput)
    new1 = forms.CharField(label="New password", widget=forms.PasswordInput)
    new2 = forms.CharField(label="Confirm new password", widget=forms.PasswordInput)

    def __init__(self, user, *a, **kw):
        self.user = user
        super().__init__(*a, **kw)
        self._style()

    def clean(self):
        cd = super().clean()
        if not self.user.check_password(cd.get("current", "")):
            self.add_error("current", "Current password is incorrect.")
        if cd.get("new1") != cd.get("new2"):
            self.add_error("new2", "Passwords do not match.")
        elif cd.get("new1"):
            try:
                validate_password(cd["new1"], self.user)
            except forms.ValidationError as e:
                self.add_error("new1", e)
        return cd


class BranchForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "address", "latitude", "longitude", "radius_m", "is_active"]

    def __init__(self, org, *a, **kw):
        super().__init__(*a, **kw)
        self.org = org
        self.fields["radius_m"].min_value = 20
        self.fields["radius_m"].max_value = 5000
        for f in ("latitude", "longitude"):
            self.fields[f].widget.attrs.update({"step": "any", "inputmode": "decimal"})
        self._style()

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Branch.objects.filter(organisation=self.org, name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("You already have a branch with that name.")
        return name

    def clean(self):
        cd = super().clean()
        if (cd.get("latitude") is None) != (cd.get("longitude") is None):
            raise forms.ValidationError("Set both latitude and longitude, or clear both.")
        return cd

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.organisation = self.org
        if commit:
            obj.save()
        return obj
