"""Platform super-admin: prices, plans, features, organisations and payments."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.db.models import Max as models_max
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Organisation

from .forms import FeatureForm, OrgPlanForm, PlanForm
from .models import Feature, Payment, Plan
from .views import plan_cards


def superuser_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *a, **kw):
        if not request.user.is_superuser:
            messages.error(request, "That page is for the platform administrator only.")
            return redirect("home")
        return view(request, *a, **kw)
    return wrapper


@superuser_required
def overview(request):
    default = Plan.objects.filter(is_default=True).first()
    all_orgs = list(Organisation.objects.select_related("plan")
                    .annotate(active=Count("members", filter=Q(members__is_active=True)))
                    .order_by("-created_at"))
    for o in all_orgs:  # resolve the plan in force without a query per organisation
        o._current_plan = o.plan if o.plan_id and not o.plan_is_expired else default
    q = request.GET.get("q", "").strip().lower()
    orgs = [o for o in all_orgs if not q or q in o.name.lower() or q in o.code.lower() or q in o.email.lower()]
    return render(request, "platform/overview.html", {"orgs": orgs, "q": q, **_platform_numbers(all_orgs)})


def _platform_numbers(all_orgs):
    """Headline numbers, revenue by month, plan mix, renewals due and recent payments."""
    from datetime import timedelta

    from django.utils import timezone

    from core.models import AttendanceRecord

    now = timezone.now()
    today = timezone.localdate()
    month_start = today.replace(day=1)
    paid = Payment.objects.filter(status=Payment.STATUS_SUCCESS)

    # Revenue for the last 6 months (by payment date)
    months = []
    y, m = month_start.year, month_start.month
    for _ in range(6):
        months.insert(0, (y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    by_month = {}
    for amt, when in paid.filter(paid_at__isnull=False).values_list("amount_kobo", "paid_at"):
        lt = timezone.localtime(when)
        by_month[(lt.year, lt.month)] = by_month.get((lt.year, lt.month), 0) + amt // 100
    from datetime import date
    peak = max([by_month.get(k, 0) for k in months] + [1])
    revenue_months = [{"label": date(yy, mm, 1).strftime("%b"), "amount": by_month.get((yy, mm), 0),
                       "h": round(by_month.get((yy, mm), 0) * 100 / peak, 1), "current": (yy, mm) == months[-1]}
                      for yy, mm in months]
    this_month, last_month = revenue_months[-1]["amount"], revenue_months[-2]["amount"]

    # Plan mix
    mix = {}
    for o in all_orgs:
        name = o._current_plan.name if o._current_plan else "None"
        mix[name] = mix.get(name, 0) + 1
    total = len(all_orgs) or 1
    plan_mix = [{"name": k, "n": v, "pct": round(v * 100 / total)} for k, v in sorted(mix.items(), key=lambda kv: -kv[1])]

    active_today = set(AttendanceRecord.objects.filter(date=today).values_list("organisation", flat=True).distinct())
    last_seen = dict(AttendanceRecord.objects.values("organisation").annotate(d=models_max("date"))
                     .values_list("organisation", "d"))
    for o in all_orgs:
        o.last_seen = last_seen.get(o.pk)
        o.active_today = o.pk in active_today

    soon = now + timedelta(days=7)
    expiring = sorted((o for o in all_orgs if o.plan_id and o.plan_expires_at and now < o.plan_expires_at <= soon),
                      key=lambda o: o.plan_expires_at)
    paying = sum(1 for o in all_orgs if o._current_plan and not o._current_plan.is_free)
    return {
        "org_count": len(all_orgs), "paying": paying, "paying_pct": round(paying * 100 / total),
        "new_this_month": sum(1 for o in all_orgs if timezone.localtime(o.created_at).date() >= month_start),
        "active_today": len(active_today),
        "revenue": sum(paid.values_list("amount_kobo", flat=True)) // 100,
        "revenue_month": this_month, "revenue_last_month": last_month,
        "revenue_change": this_month - last_month, "revenue_change_abs": abs(this_month - last_month),
        "revenue_months": revenue_months, "plan_mix": plan_mix, "expiring": expiring[:6],
        "recent_payments": paid.select_related("organisation", "plan").order_by("-paid_at", "-created_at")[:6],
    }


@superuser_required
def org_plan(request, pk):
    org = get_object_or_404(Organisation, pk=pk)
    form = OrgPlanForm(request.POST or None, instance=org)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{org.name} updated.")
        return redirect("platform")
    return render(request, "platform/org_plan.html", {
        "o": org, "form": form, "active": org.active_member_count(),
        "payments": org.payments.select_related("plan")[:20]})


@superuser_required
def plans(request):
    cards = plan_cards(Plan.objects.prefetch_related("features"))
    counts = dict(Organisation.objects.values_list("plan").annotate(n=Count("id")).values_list("plan", "n"))
    for c in cards:
        c["orgs"] = counts.get(c["plan"].pk, 0) + (counts.get(None, 0) if c["plan"].is_default else 0)
    return render(request, "platform/plans.html", {"cards": cards})


@superuser_required
def plan_edit(request, pk=None):
    plan = get_object_or_404(Plan, pk=pk) if pk else None
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        plan = form.save()
        messages.success(request, f"{plan.name} saved. The pricing page shows the change right away.")
        return redirect("platform_plans")
    return render(request, "platform/plan_form.html", {"form": form, "plan": plan})


@superuser_required
def features(request):
    return render(request, "platform/features.html", {
        "features": Feature.objects.prefetch_related("plans"), "plans": Plan.objects.all()})


@superuser_required
def feature_edit(request, pk=None):
    feature = get_object_or_404(Feature, pk=pk) if pk else None
    form = FeatureForm(request.POST or None, instance=feature)
    if request.method == "POST" and form.is_valid():
        feature = form.save()
        messages.success(request, f"“{feature.name}” saved.")
        return redirect("platform_features")
    return render(request, "platform/feature_form.html", {"form": form, "feature": feature})


@superuser_required
@require_POST
def feature_delete(request, pk):
    feature = get_object_or_404(Feature, pk=pk)
    if feature.is_builtin:
        messages.error(request, "Built-in features can't be deleted. Remove them from plans instead.")
    else:
        feature.delete()
        messages.success(request, "Feature deleted.")
    return redirect("platform_features")


@superuser_required
def payments(request):
    return render(request, "platform/payments.html", {
        "payments": Payment.objects.select_related("organisation", "plan", "created_by")[:300]})


# --------------------------------------------------------------------------- #
# Website: contact details, messages, customer quotes
# --------------------------------------------------------------------------- #
from django import forms as _forms  # noqa: E402

from core.forms import StyledMixin  # noqa: E402

from .models import ContactMessage, SiteSettings, Testimonial  # noqa: E402


class SiteSettingsForm(StyledMixin, _forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ["company_name", "sales_email", "contact_email", "whatsapp", "phone", "address", "hours"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._style()


class TestimonialForm(StyledMixin, _forms.ModelForm):
    class Meta:
        model = Testimonial
        fields = ["quote", "name", "role", "organisation", "logo", "is_published", "sort_order"]
        widgets = {"quote": _forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._style()


@superuser_required
def site_settings(request):
    form = SiteSettingsForm(request.POST or None, instance=SiteSettings.load())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Contact details saved. They now show on the website.")
        return redirect("platform_site")
    return render(request, "platform/site.html", {"form": form})


@superuser_required
def contact_messages(request):
    if request.method == "POST":
        ContactMessage.objects.filter(pk=request.POST.get("pk")).update(handled=request.POST.get("handled") == "1")
        return redirect("platform_messages")
    return render(request, "platform/messages.html", {"items": ContactMessage.objects.all()[:200]})


@superuser_required
def testimonials(request):
    return render(request, "platform/testimonials.html", {"items": Testimonial.objects.all()})


@superuser_required
def testimonial_edit(request, pk=None):
    obj = get_object_or_404(Testimonial, pk=pk) if pk else None
    if request.method == "POST" and obj and "delete" in request.POST:
        obj.delete()
        messages.success(request, "Quote deleted.")
        return redirect("platform_testimonials")
    form = TestimonialForm(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Quote saved.")
        return redirect("platform_testimonials")
    return render(request, "platform/testimonial_form.html", {"form": form, "obj": obj})
