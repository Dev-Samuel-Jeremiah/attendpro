from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from notifications.services import admins_of, notify

from .models import LeaveRequest, LeaveType

DEFAULT_TYPES = [("Annual leave", 20, True), ("Sick leave", 10, True), ("Casual leave", 5, True),
                 ("Unpaid leave", None, False)]
MAX_DAYS_BACK = 30      # sick leave etc. can be requested after the fact, within a month


class LeaveError(ValueError):
    pass


def ensure_types(org):
    if not org.leave_types.exists():
        LeaveType.objects.bulk_create([LeaveType(organisation=org, name=n, days_per_year=d, is_paid=p)
                                       for n, d, p in DEFAULT_TYPES])
    return org.leave_types.all()


def working_days(org, start, end):
    days, d = [], start
    while d <= end:
        if org.is_working_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days


def used_days(user, leave_type, year, statuses=(LeaveRequest.APPROVED,)):
    return (LeaveRequest.objects.filter(user=user, leave_type=leave_type, status__in=statuses,
                                        start_date__year=year).aggregate(n=Sum("days"))["n"] or 0)


def balances(user, year=None):
    year = year or timezone.localdate().year
    out = []
    for t in ensure_types(user.organisation).filter(is_active=True):
        used = used_days(user, t, year)
        pending = used_days(user, t, year, (LeaveRequest.PENDING,))
        out.append({"type": t, "entitled": t.days_per_year, "used": used, "pending": pending,
                    "left": None if t.days_per_year is None else max(t.days_per_year - used, 0)})
    return out


def submit(user, leave_type, start, end, reason=""):
    org = user.organisation
    today = timezone.localdate()
    if leave_type.organisation_id != org.id or not leave_type.is_active:
        raise LeaveError("Choose a leave type from the list.")
    if end < start:
        raise LeaveError("The last day can't be before the first day.")
    if start < today - timedelta(days=MAX_DAYS_BACK):
        raise LeaveError(f"Leave can be requested at most {MAX_DAYS_BACK} days after it started.")
    if start.year != end.year:
        raise LeaveError("Split leave that crosses into the next year into two requests.")
    days = len(working_days(org, start, end))
    if days == 0:
        raise LeaveError("Those dates are all non-working days.")
    if LeaveRequest.objects.filter(user=user, status__in=(LeaveRequest.PENDING, LeaveRequest.APPROVED),
                                   start_date__lte=end, end_date__gte=start).exists():
        raise LeaveError("You already have leave requested or approved on some of those days.")
    if leave_type.days_per_year is not None:
        left = leave_type.days_per_year - used_days(user, leave_type, start.year,
                                                    (LeaveRequest.APPROVED, LeaveRequest.PENDING))
        if days > left:
            raise LeaveError(f"That's {days} working day{'s' * (days != 1)}, but you have {max(left, 0)} "
                             f"{leave_type.name.lower()} day{'s' * (left != 1)} left this year "
                             f"(including requests waiting for approval).")
    req = LeaveRequest.objects.create(organisation=org, user=user, leave_type=leave_type, start_date=start,
                                      end_date=end, days=days, reason=reason)
    notify(org, [a for a in admins_of(org) if a != user], f"Leave request from {user.display_name}",
           f"{leave_type.name}: {_span(start, end)} ({days} day{'s' * (days != 1)}). {reason}".strip(),
           url=reverse("leave_admin"), kind="leave")
    return req


def _span(start, end):
    return f"{start:%d %b}" if start == end else f"{start:%d %b} – {end:%d %b %Y}"


@transaction.atomic
def approve(req, by, note=""):
    from core.models import AttendanceRecord
    req = LeaveRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != LeaveRequest.PENDING:
        raise LeaveError("This request has already been dealt with.")
    for d in working_days(req.organisation, req.start_date, req.end_date):
        rec, created = AttendanceRecord.objects.get_or_create(
            user=req.user, date=d, defaults={"organisation": req.organisation, "status": AttendanceRecord.STATUS_LEAVE,
                                             "source": "leave", "note": req.leave_type.name, "leave_request": req})
        if not created and rec.check_in is None:  # an "absent" entry becomes leave; days they came in stay
            rec.status, rec.source, rec.note, rec.leave_request = (AttendanceRecord.STATUS_LEAVE, "leave",
                                                                  req.leave_type.name, req)
            rec.save()
    _decide(req, LeaveRequest.APPROVED, by, note)
    notify(req.organisation, [req.user], "Your leave was approved",
           f"{req.leave_type.name}: {_span(req.start_date, req.end_date)}. {note}".strip(),
           url=reverse("my_leave"), kind="leave")
    return req


@transaction.atomic
def reject(req, by, note=""):
    req = LeaveRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != LeaveRequest.PENDING:
        raise LeaveError("This request has already been dealt with.")
    _decide(req, LeaveRequest.REJECTED, by, note)
    notify(req.organisation, [req.user], "Your leave request was declined",
           f"{req.leave_type.name}: {_span(req.start_date, req.end_date)}. {note}".strip(),
           url=reverse("my_leave"), kind="leave")
    return req


@transaction.atomic
def cancel(req, by, note=""):
    """Members cancel their own pending requests; admins can also withdraw approved leave."""
    req = LeaveRequest.objects.select_for_update().get(pk=req.pk)
    if not req.is_open:
        raise LeaveError("Only pending or approved leave can be cancelled.")
    was_approved = req.status == LeaveRequest.APPROVED
    req.records.filter(check_in__isnull=True).delete()
    _decide(req, LeaveRequest.CANCELLED, by, note)
    if was_approved and by != req.user:
        notify(req.organisation, [req.user], "Your approved leave was cancelled",
               f"{req.leave_type.name}: {_span(req.start_date, req.end_date)}. {note}".strip(),
               url=reverse("my_leave"), kind="leave")
    return req


def _decide(req, status, by, note):
    req.status, req.reviewed_by, req.reviewed_at, req.review_note = status, by, timezone.now(), note[:255]
    req.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])


def on_leave_today(org, day: date | None = None):
    day = day or timezone.localdate()
    return LeaveRequest.objects.filter(organisation=org, status=LeaveRequest.APPROVED,
                                       start_date__lte=day, end_date__gte=day).select_related("user", "leave_type")
