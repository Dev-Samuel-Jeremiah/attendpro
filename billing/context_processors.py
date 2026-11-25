from datetime import timedelta

from django.utils import timezone


def plan(request):
    """`plan` (the plan in force), `features` (its feature codes) and `plan_notice` for templates."""
    user = getattr(request, "user", None)
    org = getattr(user, "organisation", None) if user and user.is_authenticated else None
    if org is None:
        return {}
    from .services import in_store_app
    app = in_store_app(request)
    current = org.current_plan
    notice = None
    if org.plan_is_expired:
        notice = ("expired", f"Your {org.plan.name} plan expired on {timezone.localtime(org.plan_expires_at):%d %b %Y}. "
                             f"You're on the {current.name if current else 'free'} plan"
                             + ("." if app else " until you renew."))
    elif org.plan_id and org.plan_expires_at and org.plan_expires_at - timezone.now() < timedelta(days=7):
        notice = ("expiring", f"Your {org.plan.name} plan ends on {timezone.localtime(org.plan_expires_at):%d %b %Y}."
                              + ("" if app else " Renew to keep its features."))
    return {
        "uses_button": org.uses_button,
        "uses_qr": org.uses_qr,
        "plan": current,
        "features": current.feature_codes() if current else set(),
        "plan_notice": notice,
        "store_app": app,
    }


def site(request):
    """Public contact details for every page (Platform → Site settings)."""
    from .models import SiteSettings
    if not hasattr(request, "_site_settings"):
        request._site_settings = SiteSettings.load()
    return {"site": request._site_settings}
