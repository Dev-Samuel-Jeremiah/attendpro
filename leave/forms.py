from django import forms

from core.forms import StyledMixin

from .models import LeaveType


class LeaveRequestForm(StyledMixin, forms.Form):
    leave_type = forms.ModelChoiceField(queryset=LeaveType.objects.none(), label="Type of leave", empty_label=None)
    start_date = forms.DateField(label="First day", widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(label="Last day", widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(label="Reason (optional)", required=False, max_length=500,
                             widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, org, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["leave_type"].queryset = org.leave_types.filter(is_active=True)
        self._style()


class LeaveTypeForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ["name", "days_per_year", "is_paid", "is_active"]
        labels = {"days_per_year": "Days per year"}

    def __init__(self, org, *a, **kw):
        super().__init__(*a, **kw)
        self.org = org
        self._style()

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = LeaveType.objects.filter(organisation=self.org, name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("You already have a leave type with that name.")
        return name

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.organisation = self.org
        if commit:
            obj.save()
        return obj
