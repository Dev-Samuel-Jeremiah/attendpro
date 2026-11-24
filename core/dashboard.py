"""Numbers behind the administrator's dashboard (templates/manage/dashboard.html)."""
from collections import Counter
from datetime import datetime, timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from billing import catalog

from .models import AttendanceRecord, ScanLog

LIST_CAP = 150          # people shown per tab in "Who's in today"
TREND_DAYS = 14
ARRIVAL_DAYS = 30


def _pct(part, whole):
    return round(part * 100 / whole) if whole else 0


def _previous_working_day(org, day):
    for i in range(1, 15):
        d = day - timedelta(days=i)
        if org.is_working_day(d):
            return d
    return None


def _delta(now, before, label):
    """`+3 vs Fri` style comparison, or None when there is nothing to compare."""
    if before is None:
        return None
    diff = now - before
    return {"diff": diff, "abs": abs(diff), "up": diff > 0, "down": diff < 0, "label": label}


def _status_chip(org, now, working):
    if not working:
        return {"kind": "off", "text": "Non-working day"}
    t = now.time()
    if t < org.work_start:
        return {"kind": "soon", "text": f"Work starts at {org.work_start:%-I:%M %p}"}
    cutoff = org.late_cutoff(now.date())
    if t <= cutoff:
        return {"kind": "open", "text": f"On time until {cutoff:%-I:%M %p}"}
    if org.work_end > org.work_start and t >= org.work_end:
        return {"kind": "closed", "text": f"Check-in closed at {org.work_end:%-I:%M %p}"}
    return {"kind": "late", "text": f"Arrivals now count as late · closes {org.work_end:%-I:%M %p}"}


def _person(user, **extra):
    return {"user": user, "q": f"{user.display_name} {user.username} "
                               f"{user.department.name if user.department_id else ''}".lower(), **extra}


def _trend(org, today, total):
    start = today - timedelta(days=TREND_DAYS - 1)
    rows = (AttendanceRecord.objects.filter(organisation=org, date__gte=start, date__lte=today)
            .values("date").annotate(on_time=Count("id", filter=Q(status="present")),
                                     late=Count("id", filter=Q(status="late")),
                                     leave=Count("id", filter=Q(status="leave"))))
    by_day = {r["date"]: r for r in rows}
    scale = max([r["on_time"] + r["late"] for r in rows] + [total, 1])
    trend, rates = [], []
    for i in range(TREND_DAYS):
        d = start + timedelta(days=i)
        r = by_day.get(d, {"on_time": 0, "late": 0, "leave": 0})
        working = org.is_working_day(d)
        came = r["on_time"] + r["late"]
        rate = _pct(came, total)
        if working and d < today:
            rates.append(rate)
        trend.append({"date": d, "on_time": r["on_time"], "late": r["late"], "leave": r["leave"],
                      "working": working, "today": d == today, "rate": rate,
                      "on_time_pct": round(r["on_time"] * 100 / scale, 1),
                      "late_pct": round(r["late"] * 100 / scale, 1)})
    avg = round(sum(rates) / len(rates)) if rates else None
    past = [t for t in trend if t["working"] and not t["today"]]
    summary = None
    if past and any(t["on_time"] + t["late"] for t in past):
        summary = {"best": max(past, key=lambda t: (t["rate"], t["date"])),
                   "low": min(past, key=lambda t: (t["rate"], t["date"])),
                   "late": sum(t["late"] for t in trend),
                   "on_time_pct": _pct(sum(t["on_time"] for t in trend), sum(t["on_time"] + t["late"] for t in trend))}
    return trend, avg, scale, summary


def _arrivals(org, today):
    """Check-in times over the last 30 days, in 15-minute buckets around the start time."""
    since = today - timedelta(days=ARRIVAL_DAYS)
    times = [timezone.localtime(t) for t in AttendanceRecord.objects.filter(
        organisation=org, date__gte=since, date__lte=today, check_in__isnull=False,
    ).values_list("check_in", flat=True)[:20000]]
    if not times:
        return None
    start = datetime.combine(today, org.work_start)
    first = start - timedelta(minutes=60)
    edges = [first + timedelta(minutes=15 * i) for i in range(11)]     # 60 min before … 90 min after
    cutoff = org.late_cutoff(today)
    counts = Counter()
    total_minutes = 0
    for t in times:
        m = t.hour * 60 + t.minute
        total_minutes += m
        at = datetime.combine(today, t.time())
        if at < edges[0]:
            counts[0] += 1
        else:
            idx = min(int((at - first).total_seconds() // 900), len(edges) - 1)
            counts[idx] += 1
    peak = max(counts.values()) or 1
    buckets = []
    for i, e in enumerate(edges):
        label = f"{e:%-I:%M}"
        if i == 0:
            label = f"≤{label}"
        elif i == len(edges) - 1:
            label = f"{label}+"
        buckets.append({"label": label, "n": counts[i], "h": round(counts[i] * 100 / peak, 1),
                        "late": e.time() >= cutoff, "start": e.time() == org.work_start})
    avg = total_minutes // len(times)
    avg_time = datetime.combine(today, datetime.min.time()) + timedelta(minutes=avg)
    on_time = sum(1 for t in times if t.time() <= cutoff)
    return {"buckets": buckets, "count": len(times), "avg": f"{avg_time:%-I:%M %p}",
            "on_time_pct": _pct(on_time, len(times))}


def _punctuality(org, today, members):
    month_start = today.replace(day=1)
    rows = list(AttendanceRecord.objects.filter(organisation=org, date__gte=month_start, date__lte=today,
                                                user__in=members, status__in=["present", "late"])
                .values("user").annotate(on_time=Count("id", filter=Q(status="present")),
                                         late=Count("id", filter=Q(status="late")), days=Count("id")))
    if not rows:
        return None
    people = {u.pk: u for u in members.filter(pk__in=[r["user"] for r in rows]).select_related("department")}
    for r in rows:
        r["person"] = people.get(r["user"])
        r["pct"] = _pct(r["on_time"], r["days"])
    rows = [r for r in rows if r["person"]]
    best = sorted(rows, key=lambda r: (-r["pct"], -r["on_time"], r["person"].display_name))[:5]
    late = sorted((r for r in rows if r["late"]), key=lambda r: (-r["late"], r["person"].display_name))[:5]
    return {"best": best, "late": late, "month": month_start}


def _breakdowns(org, members, recs):
    came = recs.filter(status__in=["present", "late"])
    depts = []
    for d in org.departments.annotate(n=Count("members", filter=Q(members__is_active=True))):
        if d.n:
            p = came.filter(user__department=d).count()
            depts.append({"name": d.name, "total": d.n, "present": p, "pct": _pct(p, d.n)})
    branches = []
    if org.has_feature(catalog.MULTI_BRANCH) and org.branches.exists():
        groups = [("Main location", members.filter(branch__isnull=True), came.filter(user__branch__isnull=True))]
        groups += [(b.name, members.filter(branch=b), came.filter(user__branch=b))
                   for b in org.branches.filter(is_active=True)]
        for name, people, their in groups:
            n = people.count()
            if n:
                p = their.count()
                branches.append({"name": name, "total": n, "present": p, "pct": _pct(p, n)})
    return depts, branches


def _attention(org, today):
    items = []
    if org.has_feature(catalog.LEAVE):
        from leave.models import LeaveRequest
        n = LeaveRequest.objects.filter(organisation=org, status=LeaveRequest.PENDING).count()
        if n:
            items.append({"icon": "leave", "tone": "blue", "n": n, "url": reverse("leave_admin"),
                          "text": f"leave request{'s' if n != 1 else ''} waiting for a decision"})
    if org.has_feature(catalog.FACE):
        from faces.models import FaceProfile
        n = FaceProfile.objects.filter(organisation=org, reviewed=False).count()
        if n:
            items.append({"icon": "users", "tone": "amber", "n": n, "url": reverse("faces"),
                          "text": f"new face photo{'s' if n != 1 else ''} to confirm"})
    n = ScanLog.objects.filter(organisation=org, timestamp__date=today, action="rejected").count()
    if n:
        items.append({"icon": "alert", "tone": "red", "n": n,
                      "url": reverse("scan_logs") if org.has_feature(catalog.AUDIT_TRAIL) else "",
                      "text": f"refused check-in attempt{'s' if n != 1 else ''} today"})
    return items


def _setup(org, total):
    """First steps for a new organisation; hidden once everything is done."""
    steps = [
        {"done": org.has_location, "title": "Set your attendance location",
         "text": "So the Clock in button knows where work is.", "url": reverse("org_settings") + "#location"},
        {"done": total > 1, "title": "Add your people",
         "text": "One by one, or import a spreadsheet.", "url": reverse("members")},
        {"done": AttendanceRecord.objects.filter(organisation=org).exists(), "title": "Record the first attendance",
         "text": "Try the Clock in button or the reception QR yourself.", "url": reverse("portal")},
    ]
    done = sum(s["done"] for s in steps)
    return None if done == len(steps) else {"steps": steps, "done": done, "total": len(steps),
                                            "pct": _pct(done, len(steps))}


def admin_dashboard(org, user):
    now = timezone.localtime()
    today = now.date()
    working = org.is_working_day(today)
    members = org.members.filter(is_active=True)
    total = members.count()
    recs = AttendanceRecord.objects.filter(organisation=org, date=today).select_related("user", "user__department")

    on_time = recs.filter(status="present").count()
    late = recs.filter(status="late").count()
    leave = recs.filter(status="leave").count()
    present = on_time + late
    on_site = recs.filter(check_in__isnull=False, check_out__isnull=True).count()
    not_in = max(total - present - leave, 0)

    prev = _previous_working_day(org, today)
    prev_label = f"vs {prev:%a}" if prev else ""
    prev_present = prev_late = None
    if prev:
        agg = AttendanceRecord.objects.filter(organisation=org, date=prev).aggregate(
            p=Count("id", filter=Q(status__in=["present", "late"])), l=Count("id", filter=Q(status="late")))
        prev_present, prev_late = agg["p"], agg["l"]

    # Who's in today: one list per tab
    came = list(recs.filter(check_in__isnull=False).order_by("-check_in")[:LIST_CAP * 2])
    tabs = {
        "in": [_person(r.user, rec=r) for r in came if r.status in ("present", "late")][:LIST_CAP],
        "late": [_person(r.user, rec=r) for r in came if r.status == "late"][:LIST_CAP],
        "leave": [_person(r.user, rec=r) for r in recs.filter(status="leave")[:LIST_CAP]],
        "out": [_person(m) for m in members.exclude(attendance__date=today)
                .select_related("department").order_by("first_name", "last_name", "username")[:LIST_CAP]],
    }

    trend, trend_avg, trend_scale, trend_summary = _trend(org, today, total)
    depts, branches = _breakdowns(org, members, recs)
    donut = []
    if total:
        acc = 0
        for key, n, color in (("On time", on_time, "var(--accent)"), ("Late", late, "var(--late)"),
                              ("On leave", leave, "var(--leave)"), ("Not in yet", not_in, "#d9deea")):
            share = n * 100 / total
            donut.append({"label": key, "n": n, "pct": _pct(n, total), "color": color,
                          "from": round(acc, 2), "to": round(acc + share, 2)})
            acc += share

    return {
        "now": now, "today": today, "is_working_day": working, "chip": _status_chip(org, now, working),
        "greeting": "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening",
        "total": total, "present": present, "on_time": on_time, "late": late, "leave": leave,
        "not_in": not_in, "on_site": on_site, "rate": _pct(present, total),
        "present_delta": _delta(present, prev_present, prev_label),
        "late_delta": _delta(late, prev_late, prev_label),
        "donut": donut, "tabs": tabs, "list_cap": LIST_CAP,
        "trend": trend, "trend_avg": trend_avg, "trend_scale": trend_scale, "trend_summary": trend_summary,
        "arrivals": _arrivals(org, today), "punctuality": _punctuality(org, today, members),
        "depts": depts, "branches": branches,
        "attention": _attention(org, today), "setup": _setup(org, total),
    }


# --------------------------------------------------------------------------- #
# Staff home page (templates/staff/portal.html)
# --------------------------------------------------------------------------- #
def staff_home(user, rec):
    org = user.organisation
    now = timezone.localtime()
    today = now.date()
    recs = {r.date: r for r in AttendanceRecord.objects.filter(user=user, date__gte=today - timedelta(days=120),
                                                               date__lte=today)}

    week_start = today - timedelta(days=today.weekday())
    week = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        r = recs.get(d)
        if r:
            state = r.status
        elif d > today:
            state = "future"
        elif not org.is_working_day(d):
            state = "off"
        elif d == today:
            state = "pending"
        else:
            state = "absent"
        week.append({"date": d, "state": state, "rec": r, "today": d == today})

    # On-time streak: working days in a row arriving on time (leave days don't break it)
    streak = 0
    d = today if (rec and rec.check_in) else today - timedelta(days=1)
    for _ in range(120):
        r = recs.get(d)
        if org.is_working_day(d) or r:
            if r and r.status == "present":
                streak += 1
            elif not (r and r.status == "leave"):
                break
        d -= timedelta(days=1)

    month_ins = [timezone.localtime(r.check_in) for r in recs.values()
                 if r.check_in and r.date >= today.replace(day=1)]
    avg_arrival = None
    if month_ins:
        mins = sum(t.hour * 60 + t.minute for t in month_ins) // len(month_ins)
        avg_arrival = (datetime.combine(today, datetime.min.time()) + timedelta(minutes=mins)).strftime("%-I:%M %p")

    leave = []
    if org.has_feature(catalog.LEAVE):
        from leave.models import LeaveRequest
        leave = list(LeaveRequest.objects.filter(user=user, end_date__gte=today,
                                                 status__in=[LeaveRequest.PENDING, LeaveRequest.APPROVED])
                     .select_related("leave_type").order_by("start_date")[:3])

    on_site_since = rec.check_in if rec and rec.check_in and not rec.check_out else None
    return {"now": now, "week": week, "streak": streak, "avg_arrival": avg_arrival, "upcoming_leave": leave,
            "on_site_since": on_site_since,
            "chip": _status_chip(org, now, org.is_working_day(today)),
            "greeting": "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"}
