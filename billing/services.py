import hashlib
import hmac
import json
import secrets
import urllib.error
import urllib.request
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone

from .models import Feature, Payment, Plan

PAYSTACK_API = "https://api.paystack.co"


# --------------------------------------------------------------------------- #
# Feature gating
# --------------------------------------------------------------------------- #
def cheapest_plan_with(code):
    return Plan.objects.filter(is_public=True, features__code=code).order_by("price").first()


def upgrade_message(code):
    feature = Feature.objects.filter(code=code).first()
    plan = cheapest_plan_with(code)
    name = feature.name if feature else "This feature"
    if plan:
        return f"{name} is available on the {plan.name} plan. Upgrade to use it."
    return f"{name} isn't included in your plan."


def feature_required(code):
    """View decorator: send organisations without `code` in their plan to the billing page."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *a, **kw):
            org = getattr(request.user, "organisation", None)
            if org is None or not org.has_feature(code):
                messages.warning(request, upgrade_message(code))
                return redirect("billing" if getattr(request.user, "is_org_admin", False) else "home")
            return view(request, *a, **kw)
        return wrapper
    return deco


def staff_limit_message(org):
    plan = org.current_plan
    return (f"Your {plan.name} plan allows {org.staff_limit} active accounts (admins included). "
            f"Deactivate someone or upgrade your plan to add more.")


# --------------------------------------------------------------------------- #
# Paystack
# --------------------------------------------------------------------------- #
class PaystackError(Exception):
    pass


def paystack_enabled():
    return bool(settings.PAYSTACK_SECRET_KEY)


def _paystack(method, path, payload=None):
    req = urllib.request.Request(
        PAYSTACK_API + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                 "Content-Type": "application/json", "User-Agent": "AttendPro"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("message", str(e))
        except ValueError:
            msg = str(e)
        raise PaystackError(msg) from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise PaystackError("Could not reach Paystack. Please try again.") from e
    if not body.get("status"):
        raise PaystackError(body.get("message", "Paystack refused the request."))
    return body["data"]


def start_checkout(org, plan, user, callback_url):
    """Create a pending Payment and return the Paystack page to send the payer to."""
    email = user.email or org.email
    if not email:
        raise PaystackError("Add an email address to your profile or organisation settings first.")
    payment = Payment.objects.create(
        organisation=org, plan=plan, amount_kobo=plan.price * 100, created_by=user,
        reference=f"AP-{org.code}-{secrets.token_hex(6)}".upper())
    data = _paystack("POST", "/transaction/initialize", {
        "email": email, "amount": payment.amount_kobo, "currency": "NGN",
        "reference": payment.reference, "callback_url": callback_url,
        "metadata": {"organisation": org.code, "plan": plan.slug, "payment_id": payment.pk},
    })
    return data["authorization_url"]


def verify_and_apply(reference):
    """Ask Paystack about a reference and activate the plan if paid. Safe to call repeatedly."""
    payment = Payment.objects.filter(reference=reference).select_related("plan", "organisation").first()
    if payment is None:
        return None
    if payment.status == Payment.STATUS_SUCCESS:
        return payment
    data = _paystack("GET", f"/transaction/verify/{reference}")
    return apply_paystack_result(payment, data)


def apply_paystack_result(payment, data):
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related("plan", "organisation").get(pk=payment.pk)
        if payment.status == Payment.STATUS_SUCCESS:
            return payment
        paid = (data.get("status") == "success" and int(data.get("amount") or 0) == payment.amount_kobo
                and (data.get("currency") or "NGN") == "NGN")
        if not paid:
            if data.get("status") in ("failed", "abandoned", "reversed"):
                payment.status = Payment.STATUS_FAILED
                payment.save(update_fields=["status"])
            return payment
        start, end = activate_plan(payment.organisation, payment.plan)
        payment.status = Payment.STATUS_SUCCESS
        payment.channel = (data.get("channel") or "")[:30]
        payment.paid_at = timezone.now()
        payment.period_start, payment.period_end = start, end
        payment.save()
    return payment


def activate_plan(org, plan, days=None):
    """Put `org` on `plan` for one period. Renewing the same plan early extends from the current
    expiry; switching plans starts the new period now."""
    from core.models import Organisation
    org = Organisation.objects.select_for_update().get(pk=org.pk)
    now = timezone.now()
    start = now
    if org.plan_id == plan.id and org.plan_expires_at and org.plan_expires_at > now:
        start = org.plan_expires_at
    end = start + timedelta(days=days or plan.period_days)
    org.plan, org.plan_expires_at = plan, end
    org.save(update_fields=["plan", "plan_expires_at"])
    return start, end


def valid_webhook_signature(body: bytes, signature: str) -> bool:
    if not settings.PAYSTACK_SECRET_KEY or not signature:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
