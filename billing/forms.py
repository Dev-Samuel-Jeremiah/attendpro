from django import forms
from django.utils.text import slugify

from core.forms import StyledMixin
from core.models import Organisation

from .models import Feature, Plan


class PlanForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Plan
        fields = ["name", "tagline", "price", "period_days", "staff_limit", "features",
                  "is_public", "highlight", "sort_order"]
        labels = {"price": "Price (₦)", "period_days": "Billing period (days)",
                  "staff_limit": "Staff limit", "is_public": "Show on pricing page",
                  "highlight": "Mark as “Most popular”", "sort_order": "Order"}
        widgets = {"features": forms.CheckboxSelectMultiple}
        help_texts = {"is_public": "", "highlight": ""}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["features"].queryset = Feature.objects.all()
        self.fields["features"].label = ""
        self.fields["features"].label_from_instance = (
            lambda f: f"{f.name}{' (coming soon)' if f.coming_soon else ''}")
        self._style()

    def clean(self):
        cd = super().clean()
        if self.instance.is_default and cd.get("price"):
            self.add_error("price", "The default plan is the free fallback, so its price must stay 0.")
        if cd.get("price") and not cd.get("period_days"):
            self.add_error("period_days", "A paid plan needs a billing period.")
        return cd

    def save(self, commit=True):
        plan = super().save(commit=False)
        if not plan.slug:
            base = slugify(plan.name) or "plan"
            slug, n = base, 2
            while Plan.objects.filter(slug=slug).exists():
                slug, n = f"{base}-{n}", n + 1
            plan.slug = slug
        if commit:
            plan.save()
            self.save_m2m()
        return plan


class FeatureForm(StyledMixin, forms.ModelForm):
    plans = forms.ModelMultipleChoiceField(queryset=Plan.objects.all(), required=False,
                                           widget=forms.CheckboxSelectMultiple,
                                           label="Included in")

    class Meta:
        model = Feature
        fields = ["name", "description", "status", "sort_order"]
        labels = {"sort_order": "Order"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.instance.pk:
            self.fields["plans"].initial = list(self.instance.plans.all())
        self._style()

    def save(self, commit=True):
        feature = super().save(commit=False)
        if not feature.code:
            base = slugify(feature.name).replace("-", "_")[:34] or "feature"
            code, n = base, 2
            while Feature.objects.filter(code=code).exists():
                code, n = f"{base}_{n}", n + 1
            feature.code = code
        feature.save()
        feature.plans.set(self.cleaned_data["plans"])
        return feature


class OrgPlanForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Organisation
        fields = ["plan", "plan_expires_at"]
        labels = {"plan": "Plan", "plan_expires_at": "Expires"}
        widgets = {"plan_expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"},
                                                          format="%Y-%m-%dT%H:%M")}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["plan"].empty_label = "Default (free) plan"
        self.fields["plan_expires_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self._style()
