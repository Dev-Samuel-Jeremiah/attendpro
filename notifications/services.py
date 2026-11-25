"""Send notifications: always in-app, and by email when the server has an SMTP account
(EMAIL_HOST) and the organisation hasn't switched email off. Only organisations whose plan
includes automated notifications get any."""
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.mail import get_connection
from django.db import IntegrityError, transaction
from django.utils import timezone

from billing import catalog

from .models import AlertLog, Notification

log = logging.getLogger(__name__)


def email_enabled():
    return bool(settings.EMAIL_HOST)


def admins_of(org):
    from core.models import User
    return list(org.members.filter(role=User.ROLE_ADMIN, is_active=True))


def _absolute(url):
    if not url or url.startswith("http"):
        return url
    return (settings.ATTENDPRO_PUBLIC_URL or "https://attendpro.cloud") + url


def notify(org, users, title, body="", url="", kind="info", email=True):
    """Notify `users` (members of `org`). Returns how many in-app notifications were created."""
    if org is None or not org.has_feature(catalog.NOTIFICATIONS):
        return 0
    users = [u for u in users if u is not None and u.is_active]
    if not users:
        return 0
    Notification.objects.bulk_create([
        Notification(organisation=org, user=u, kind=kind, title=title[:160], body=body[:500], url=url[:255])
        for u in users])
    if email and org.email_notifications and email_enabled():
        _send_emails(org, [u for u in users if u.email], title, body, url)
    return len(users)


def _send_emails(org, users, title, body, url):
    if not users:
        return
    from django.core.mail import EmailMultiAlternatives

    from billing.emails import render_html
    link = _absolute(url)
    subject = f"{title} · {org.name}"
    text = f"{body}\n\n{('Open AttendPro: ' + link) if link else ''}\n\n— {org.name} on AttendPro".strip()
    html = render_html("emails/notification.html", subject, kicker=org.name, heading=title, body=body,
                       link=link, org=org)
    messages = []
    for u in users:
        m = EmailMultiAlternatives(subject=subject, body=text, to=[u.email])
        m.attach_alternative(html, "text/html")
        messages.append(m)
    try:
        get_connection(fail_silently=False).send_messages(messages)
    except Exception:  # a mail problem must never break attendance
        log.exception("Sending %d notification email(s) for %s failed", len(messages), org.code)


def once(org, day, kind):
    """True the first time it's called for (org, day, kind); False after that."""
    try:
        with transaction.atomic():
            AlertLog.objects.create(organisation=org, date=day, kind=kind)
        return True
    except IntegrityError:
        return False


# --------------------------------------------------------------------------- #
# Scheduled alerts (run every few minutes by `manage.py send_alerts`)
# --------------------------------------------------------------------------- #
ABSENCE_ALERT_AFTER = timedelta(hours=1)      # after the late cut-off
CHECKOUT_REMINDER_AFTER = timedelta(hours=2)  # after work end
PLAN_REMINDER_DAYS = (7, 3, 1)


def run_scheduled_alerts(now=None):
    """Returns a list of (org code, alert kind, people notified) for logging."""
    from core.models import AttendanceRecord, Organisation
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    sent = []
    Notification.objects.filter(read_at__lt=now - timedelta(days=90)).delete()
    AlertLog.objects.filter(date__lt=today - timedelta(days=30)).delete()
    for org in Organisation.objects.select_related("plan"):
        if not org.has_feature(catalog.NOTIFICATIONS):
            continue
        working = org.is_working_day(today)
        tz = now.tzinfo

        late_cutoff = timezone.make_aware(datetime.combine(today, org.late_cutoff(today)), tz)
        if working and org.notify_absent and now >= late_cutoff + ABSENCE_ALERT_AFTER and once(org, today, "absent"):
            in_today = AttendanceRecord.objects.filter(organisation=org, date=today).values_list("user_id", flat=True)
            absent = list(org.members.filter(is_active=True, date_joined__date__lt=today)
                          .exclude(id__in=list(in_today)).order_by("first_name"))
            if absent:
                for m in absent:
                    notify(org, [m], "You haven't clocked in today",
                           f"Work started at {org.work_start:%I:%M %p}. If you're at work, clock in now; "
                           f"if you're away, ask your administrator to record it.", url="/me/", kind="absent")
                names = ", ".join(m.display_name for m in absent[:12]) + (" and others" if len(absent) > 12 else "")
                notify(org, admins_of(org), f"{len(absent)} {'person has' if len(absent) == 1 else 'people have'} "
                       f"not clocked in today", names, url=f"/manage/attendance/?date={today}", kind="absent")
                sent.append((org.code, "absent", len(absent)))

        work_end = timezone.make_aware(datetime.combine(today, org.work_end), tz)
        if (working and org.notify_checkout and org.work_end > org.work_start
                and now >= work_end + CHECKOUT_REMINDER_AFTER and once(org, today, "checkout")):
            open_recs = (AttendanceRecord.objects.filter(organisation=org, date=today, check_in__isnull=False,
                                                         check_out__isnull=True).select_related("user"))
            people = [r.user for r in open_recs]
            for u in people:
                notify(org, [u], "You didn't clock out today",
                       "Clock out when you leave so your hours are counted. If you've already left, "
                       "ask your administrator to add your departure time.", url="/me/", kind="checkout")
            if people:
                sent.append((org.code, "checkout", len(people)))

        if org.plan_id and org.plan_expires_at and not org.plan.is_free:
            days_left = (timezone.localtime(org.plan_expires_at).date() - today).days
            if days_left in PLAN_REMINDER_DAYS and once(org, today, f"plan_{days_left}"):
                when = "tomorrow" if days_left == 1 else f"in {days_left} days"
                notify(org, admins_of(org), f"Your {org.plan.name} plan ends {when}",
                       f"It ends on {timezone.localtime(org.plan_expires_at):%d %b %Y}. After that its "
                       f"features pause until the plan is renewed; nothing is deleted.",
                       url="/manage/billing/", kind="plan")
                sent.append((org.code, f"plan_{days_left}", 1))
    return sent
