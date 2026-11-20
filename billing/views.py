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


def pricing(request):
    return render(request, "billing/pricing.html", {"cards": plan_cards(_public_plans())})


@org_admin_required
def billing(request):
    org = request.user.organisation
    return render(request, "billing/billing.html", {
        "cards": plan_cards(_public_plans()),
        "members_used": org.active_member_count(),
        "payments": org.payments.select_related("plan")[:20],
        "paystack": services.paystack_enabled(),
    })


@org_admin_required
@require_POST
def checkout(request, slug):
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
                                      request.build_absolute_uri(reverse("paystack_callback")))
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
        messages.success(request, f"Payment received. You're on the {payment.plan.name} plan until "
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
