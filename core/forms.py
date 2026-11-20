from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password

from .models import AttendanceRecord, Department, Organisation, User


class StyledMixin:
    def _style(self):
        for f in self.fields.values():
            w = f.widget
            if isinstance(w, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                continue
            w.attrs.setdefault("class", "input")


class LoginForm(StyledMixin, forms.Form):
    username = forms.CharField(label="ID", widget=forms.TextInput(attrs={
        "placeholder": "e.g. TMY-0001", "autocomplete": "username", "autocapitalize": "characters"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        "placeholder": "Password", "autocomplete": "current-password"}))

    def __init__(self, request=None, *a, **kw):
        self.request = request
        self.user = None
        super().__init__(*a, **kw)
        self._style()

    def clean(self):
        cd = super().clean()
        u, p = cd.get("username", "").strip(), cd.get("password")
        if u and p:
            user = authenticate(self.request, username=u, password=p) or \
                   authenticate(self.request, username=u.upper(), password=p)
            if user is None:
                raise forms.ValidationError("Incorrect ID or password.")
            if not user.is_active:
                raise forms.ValidationError("This account has been deactivated. Contact your administrator.")
            self.user = user
        return cd


class OrgRegisterForm(StyledMixin, forms.Form):
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
        self._style()

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if not code.isalnum():
            raise forms.ValidationError("Use letters and numbers only.")
        if Organisation.objects.filter(code=code).exists():
            raise forms.ValidationError("This code is already in use.")
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
        fields = ["first_name", "last_name", "category", "department", "designation", "email", "phone",
                  "photo", "role", "is_active"]
        labels = {"designation": "Job title / class", "role": "Access level", "is_active": "Active"}

    def __init__(self, org, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["department"].queryset = Department.objects.filter(organisation=org)
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
                  "grace_minutes", "checkout_gap_minutes", "qr_rotation_seconds",
                  "latitude", "longitude", "location_radius_m"]
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

    def __init__(self, *a, branding=True, **kw):
        super().__init__(*a, **kw)
        if not branding:
            del self.fields["logo"]  # custom branding is a plan feature
        self.fields["working_days_choice"].initial = [str(d) for d in self.instance.working_day_list()]
        self.fields["qr_rotation_seconds"].min_value = 10
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
    check_in_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}))
    check_out_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}))

    class Meta:
        model = AttendanceRecord
        fields = ["user", "date", "status", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, org, *a, **kw):
        super().__init__(*a, **kw)
        self.org = org
        self.fields["user"].queryset = org.members.filter(is_active=True)
        self.fields["user"].label = "Member"
        from django.utils import timezone
        if self.instance.pk:
            if self.instance.check_in:
                self.fields["check_in_time"].initial = timezone.localtime(self.instance.check_in).strftime("%H:%M")
            if self.instance.check_out:
                self.fields["check_out_time"].initial = timezone.localtime(self.instance.check_out).strftime("%H:%M")
        self._style()

    def clean(self):
        cd = super().clean()
        user, d = cd.get("user"), cd.get("date")
        if user and d:
            qs = AttendanceRecord.objects.filter(user=user, date=d)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("A record already exists for this member on this date — edit that one instead.")
        ci, co = cd.get("check_in_time"), cd.get("check_out_time")
        if ci and co and co <= ci:
            self.add_error("check_out_time", "Check-out must be after check-in.")
        return cd

    def save(self, commit=True):
        from datetime import datetime
        from django.utils import timezone
        rec = super().save(commit=False)
        rec.organisation = self.org
        rec.source = "manual"
        tz = timezone.get_current_timezone()
        ci, co = self.cleaned_data.get("check_in_time"), self.cleaned_data.get("check_out_time")
        rec.check_in = timezone.make_aware(datetime.combine(rec.date, ci), tz) if ci else None
        rec.check_out = timezone.make_aware(datetime.combine(rec.date, co), tz) if co else None
        if commit:
            rec.save()
        return rec


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
