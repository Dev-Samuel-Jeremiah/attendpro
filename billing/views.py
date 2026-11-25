import json
import logging

from django.contrib import messages
from django.db.models import Prefetch
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.decorators import org_admin_required

from . import services
from .models import Feature, Payment, Plan

log = logging.getLogger(__name__)


def plan_cards(plans):
    """Plans with their feature lists, each after the first shown as “Everything in X, plus …”.
    One feature of the cheaper plan may be missing (Enterprise swaps “One branch” for
    “Multiple branches”) and it still reads as “everything in”."""
    cards, prev = [], None
    for p in plans:
        feats = list(p.features.all())
        if prev is not None and prev["codes"] and len(prev["codes"] - {f.code for f in feats}) <= 1:
            extra = [f for f in feats if f.code not in prev["codes"]]
            cards.append({"plan": p, "base": prev["plan"], "features": extra, "codes": {f.code for f in feats}})
        else:
            cards.append({"plan": p, "base": None, "features": feats, "codes": {f.code for f in feats}})
        prev = cards[-1]
    return cards


def _public_plans():
    return Plan.objects.filter(is_public=True).prefetch_related(
        Prefetch("features", queryset=Feature.objects.order_by("sort_order", "name")))


def _cycle(request):
    return "yearly" if request.GET.get("cycle") == "yearly" else "monthly"


# How the comparison table groups the built-in features; features the super admin adds go under "More".
COMPARE_GROUPS = [
    ("Clocking in", ["manual_clock", "clock_in_out", "qr_attendance", "geofencing", "face_verification"]),
    ("Day to day", ["daily_dashboard", "attendance_history", "leave_management", "self_service", "notifications"]),
    ("Reports & data", ["advanced_reports", "exports", "advanced_analytics", "audit_trail", "payroll", "advanced_backup"]),
    ("Your organisation", ["single_branch", "multi_branch", "custom_branding", "priority_support"]),
]
PLAN_ICONS = ["pin", "qr", "layers", "star"]


def pricing_context(cycle):
    """Everything the pricing page (and the home page's pricing section) needs, from the live plans."""
    plans = list(_public_plans())
    cards = plan_cards(plans)
    for i, c in enumerate(cards):
        p = c["plan"]
        c["icon"] = PLAN_ICONS[min(i, len(PLAN_ICONS) - 1)]
        c["saving_pct"] = round(p.yearly_saving * 100 / (p.price * 12)) if p.has_yearly else 0
        c["top"], c["more"] = c["features"][:6], max(len(c["features"]) - 6, 0)
    features = Feature.objects.order_by("sort_order", "name")
    by_code = {f.code: f for f in features}
    plan_codes = [set(p.features.values_list("code", flat=True)) for p in plans]
    seen, groups = set(), []
    for title, codes in COMPARE_GROUPS:
        rows = [by_code[c] for c in codes if c in by_code]
        seen.update(f.code for f in rows)
        groups.append((title, rows))
    extra = [f for f in features if f.code not in seen and any(f.code in pc for pc in plan_codes)]
    if extra:
        groups.append(("More", extra))
    groups = [(t, [{"feature": f, "has": [f.code in pc for pc in plan_codes]} for f in rows]) for t, rows in groups if rows]
    return {
        "cards": cards, "plans": plans, "groups": groups, "cycle": cycle,
        "hot_index": next((i for i, p in enumerate(plans) if p.highlight), -1),
        "max_saving_pct": max([c["saving_pct"] for c in cards] or [0]),
        "plans_json": [{"name": p.name, "slug": p.slug, "limit": p.staff_limit, "price": p.price,
                        "yearly": p.yearly_price if p.has_yearly else None, "free": p.is_free} for p in plans],
    }


def pricing(request):
    if services.in_store_app(request):          # no prices inside the store apps
        return redirect("home")
    return render(request, "billing/pricing.html", pricing_context(_cycle(request)))


@org_admin_required
def billing(request):
    org = request.user.organisation
    return render(request, "billing/billing.html", {
        "cards": plan_cards(_public_plans()), "cycle": _cycle(request),
        "members_used": org.active_member_count(),
        "payments": org.payments.select_related("plan")[:20],
        "paystack": services.paystack_enabled(),
    })


@org_admin_required
@require_POST
def checkout(request, slug):
    if services.in_store_app(request):
        messages.info(request, "Plan changes aren't available in the app.")
        return redirect("billing")
    org = request.user.organisation
    plan = get_object_or_404(Plan, slug=slug, is_public=True)
    if plan.is_free:
        messages.info(request, "That plan is free; there is nothing to pay.")
        return redirect("billing")
    if not services.paystack_enabled():
        messages.error(request, "Online payment isn't switched on yet. Please contact support to upgrade.")
        return redirect("billing")
    limit = plan.staff_limit
    if limit is not None and org.active_member_count() > limit:
        messages.error(request, f"You have {org.active_member_count()} active accounts but {plan.name} allows "
                                f"{limit}. Deactivate some first, or choose a bigger plan.")
        return redirect("billing")
    try:
        url = services.start_checkout(org, plan, request.user,
                                      request.build_absolute_uri(reverse("paystack_callback")),
                                      cycle=request.POST.get("cycle"))
    except services.PaystackError as e:
        messages.error(request, f"Payment could not be started: {e}")
        return redirect("billing")
    return redirect(url)


@org_admin_required
def paystack_callback(request):
    """Paystack sends the payer back here with ?reference=…"""
    ref = request.GET.get("reference") or request.GET.get("trxref") or ""
    payment = Payment.objects.filter(reference=ref, organisation=request.user.organisation).first()
    if payment is None:
        messages.error(request, "We couldn't find that payment.")
        return redirect("billing")
    try:
        payment = services.verify_and_apply(ref)
    except services.PaystackError as e:
        messages.warning(request, f"We couldn't confirm the payment yet ({e}). "
                                  "If you were charged, your plan will update within a few minutes.")
        return redirect("billing")
    if payment.status == Payment.STATUS_SUCCESS:
        messages.success(request, f"Payment received ({payment.get_cycle_display().lower()}). You're on the {payment.plan.name} plan until "
                                  f"{payment.period_end:%d %b %Y}.")
    elif payment.status == Payment.STATUS_FAILED:
        messages.error(request, "The payment didn't go through. You have not been charged.")
    else:
        messages.info(request, "Your payment is still processing. Your plan will update once it's confirmed.")
    return redirect("billing")


@csrf_exempt
@require_POST
def paystack_webhook(request):
    """Paystack calls this for every payment event, even if the payer closes the browser."""
    if not services.valid_webhook_signature(request.body, request.headers.get("X-Paystack-Signature", "")):
        return HttpResponseBadRequest("bad signature")
    try:
        event = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("bad json")
    data = event.get("data") or {}
    if event.get("event") == "charge.success":
        payment = Payment.objects.filter(reference=data.get("reference", "")).first()
        if payment:
            services.apply_paystack_result(payment, data)
        else:
            log.warning("Paystack webhook for unknown reference %s", data.get("reference"))
    return HttpResponse("ok")
