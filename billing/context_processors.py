from datetime import timedelta

from django.utils import timezone


def plan(request):
    """`plan` (the plan in force), `features` (its feature codes) and `plan_notice` for templates."""
    user = getattr(request, "user", None)
    org = getattr(user, "organisation", None) if user and user.is_authenticated else None
    if org is None:
        return {}
    current = org.current_plan
    notice = None
    if org.plan_is_expired:
        notice = ("expired", f"Your {org.plan.name} plan expired on {timezone.localtime(org.plan_expires_at):%d %b %Y}. "
                             f"You're on the {current.name if current else 'free'} plan until you renew.")
    elif org.plan_id and org.plan_expires_at and org.plan_expires_at - timezone.now() < timedelta(days=7):
        notice = ("expiring", f"Your {org.plan.name} plan ends on {timezone.localtime(org.plan_expires_at):%d %b %Y}. "
                              f"Renew to keep its features.")
    return {
        "uses_button": org.uses_button,
        "uses_qr": org.uses_qr,
        "plan": current,
        "features": current.feature_codes() if current else set(),
        "plan_notice": notice,
    }
