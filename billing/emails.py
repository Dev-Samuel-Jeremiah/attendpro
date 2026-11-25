"""Emails from AttendPro to organisation administrators: a welcome after sign-up, and an
occasional note about bigger plans.

These go by email only. The Android / iPhone apps never show prices or point to payments (store
rules), but contacting customers outside the app about plans is allowed, so this is how people who
signed up in the app hear about upgrading. Nothing is sent until the server has an email account
(EMAIL_HOST in .env)."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Min
from django.template.loader import render_to_string
from django.utils import timezone

log = logging.getLogger(__name__)

UPSELL_EVERY_DAYS = 14


def _site_url(path=""):
    return (settings.ATTENDPRO_PUBLIC_URL or "https://attendpro.cloud").rstrip("/") + path


def email_context(subject, **extra):
    """What every HTML email (templates/emails/) needs."""
    from .models import SiteSettings
    return {"subject": subject, "site": SiteSettings.load(), "site_url": _site_url(),
            "logo_url": _site_url("/static/brand/email-mark.png"), "year": timezone.localdate().year, **extra}


def render_html(template, subject, **extra):
    return render_to_string(template, email_context(subject, **extra))


def _send(to, subject, body, html=None):
    """Plain text for every mail app, plus the designed HTML version where it can be shown."""
    if not settings.EMAIL_HOST or not to:
        return False
    from .models import SiteSettings
    site = SiteSettings.load()
    reply = [e for e in (site.sales_email, site.contact_email) if e][:1]
    try:
        msg = EmailMultiAlternatives(subject, body, to=[to], reply_to=reply or None)
        if html:
            msg.attach_alternative(html, "text/html")
        msg.send()
        return True
    except Exception:  # email trouble must never break sign-up or the page
        log.exception("Couldn't send %r to an administrator", subject)
        return False


def _contact_line():
    from .models import SiteSettings
    site = SiteSettings.load()
    bits = []
    if site.whatsapp:
        bits.append(f"WhatsApp {site.whatsapp}")
    if site.phone:
        bits.append(f"call {site.phone}")
    return ("Questions? Reply to this email" + (", " + " or ".join(bits) if bits else "") + ".")


def welcome(org, admin):
    """Straight after an organisation signs up (website or app)."""
    from .models import Plan
    plan = org.current_plan
    paid = Plan.objects.filter(is_public=True, price__gt=0).aggregate(m=Min("price"))["m"]
    lines = [
        f"Hi {admin.first_name or 'there'},",
        "",
        f"Welcome to AttendPro! {org.name} is ready.",
        "",
        f"Your administrator ID: {admin.username}",
        "Sign in with it and your password in the AttendPro app or at " + _site_url("/login/"),
        "",
        "Three steps to get going:",
        "1. Settings: set your attendance location (or turn on the reception QR screen).",
        "2. Members: add your people one by one, or import a spreadsheet.",
        "3. Clock in yourself once, to see how it works.",
        "",
    ]
    if plan and plan.is_free:
        limit = plan.staff_limit or 10
        lines += [f"Your plan: {plan.name} (free), for up to {limit} people.",
                  "For bigger teams, QR attendance, reports, leave, payroll and more, see the plans"
                  + (f" (from ₦{paid:,} a month)" if paid else "") + ": " + _site_url("/pricing/"),
                  ""]
    elif plan:
        lines += [f"Your plan: {plan.name}.", ""]
    lines += [
        "TO CHANGE YOUR PLAN OR MAKE A PAYMENT",
        "Visit our website in a web browser (on a computer, or Chrome / Safari on your phone):",
        _site_url("/manage/billing/"),
        f"Sign in with your administrator ID ({admin.username}) and open Plan & billing. You can pay by card, "
        "bank transfer or USSD. Plan changes and payments can't be made inside the AttendPro mobile app, "
        "but your new plan works in the app straight away.",
        "",
    ]
    lines += [_contact_line(), "", "The AttendPro team"]
    subject = f"Welcome to AttendPro, {admin.first_name or org.name}"
    html = render_html("emails/welcome.html", subject, kicker="Welcome to AttendPro",
                       heading=f"{org.name} is ready", org=org, admin=admin, plan=plan, cheapest_paid=paid,
                       login_url=_site_url("/login/"), billing_url=_site_url("/manage/billing/"),
                       pricing_url=_site_url("/pricing/"), contact_line=_contact_line(),
                       steps=[("Set your attendance location",
                               "In Settings, so the Clock in button knows where work is. Or switch on the reception QR screen."),
                              ("Add your people",
                               "In Members, one by one or by importing a spreadsheet. Each person gets their own ID."),
                              ("Clock in yourself",
                               "Try it once in the AttendPro app to see exactly what your team will see.")])
    return _send(admin.email, subject, "\n".join(lines), html)


def upgrade_nudge(org, user, reason, feature_code=None):
    """When an administrator reaches the free plan's people limit or opens a feature their plan
    doesn't include. At most once every UPSELL_EVERY_DAYS days per organisation."""
    from notifications.models import AlertLog

    from .models import Feature
    from .services import cheapest_plan_with
    if not settings.EMAIL_HOST or not user or not getattr(user, "is_org_admin", False) or not user.email:
        return False
    today = timezone.localdate()
    if AlertLog.objects.filter(organisation=org, kind="upsell",
                               date__gt=today - timedelta(days=UPSELL_EVERY_DAYS)).exists():
        return False
    AlertLog.objects.get_or_create(organisation=org, date=today, kind="upsell")

    from .models import Plan
    plan = org.current_plan
    if reason == "staff_limit":
        what = (f"{org.name} has reached the {org.staff_limit} people allowed on the {plan.name} plan. "
                f"A bigger plan lets you add everyone.")
        target = next((p for p in Plan.objects.filter(is_public=True, price__gt=0).order_by("price")
                       if p.staff_limit is None or (org.staff_limit and p.staff_limit > org.staff_limit)), None)
        heading = "Your team is growing"
    else:
        feature = Feature.objects.filter(code=feature_code).first()
        target = cheapest_plan_with(feature_code) if feature_code else None
        what = (f"You opened {feature.name if feature else 'a feature'}, which is part of the "
                f"{target.name if target else 'paid'} plan.")
        heading = f"Unlock {feature.name}" if feature else "Unlock more of AttendPro"
    lines = [f"Hi {user.first_name or 'there'},", "", what, ""]
    if target and not target.is_free:
        lines.append(f"{target.name} is ₦{target.price:,} a month"
                     + (f", or ₦{target.yearly_price:,} a year" if target.has_yearly else "") + ".")
    lines += ["Compare plans: " + _site_url("/pricing/"),
              "Upgrade: sign in at " + _site_url("/manage/billing/") + " (on a computer or in your phone's browser) "
              "and pay by card, transfer or USSD. The new plan works in the app straight away.",
              "Plans never renew automatically, and you can ask for a full refund within 7 days.",
              "", _contact_line(), "", "The AttendPro team"]
    subject = f"Grow {org.name} with AttendPro" + (f" {target.name}" if target and not target.is_free else "")
    highlights = []
    if target is not None:  # what the bigger plan adds, starting with the feature they tried to open
        have = set(plan.features.values_list("pk", flat=True)) if plan else set()
        extra = [f for f in target.features.all() if f.pk not in have]
        extra.sort(key=lambda f: f.code != feature_code)
        highlights = [f.name for f in extra[:5]]
    html = render_html("emails/upgrade.html", subject, kicker=f"{org.name} · {plan.name} plan", heading=heading,
                       org=org, user=user, intro=what, target=target, highlights=highlights,
                       billing_url=_site_url("/manage/billing/"), pricing_url=_site_url("/pricing/"),
                       contact_line=_contact_line())
    return _send(user.email, subject, "\n".join(lines), html)
