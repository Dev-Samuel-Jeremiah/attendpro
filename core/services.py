"""Business logic: rotating QR tokens, marking attendance, and reports."""
import csv
import hashlib
import hmac
import io
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from billing import catalog
from notifications.services import admins_of, notify

from .models import AttendanceRecord, Branch, Organisation, ScanLog, User


# --------------------------------------------------------------------------- #
# Rotating QR tokens
# --------------------------------------------------------------------------- #
def _sign(org: Organisation, window, branch: Branch | None = None) -> str:
    msg = (f"{org.id}:{org.kiosk_key}:{window}" if branch is None
           else f"{org.id}:b{branch.id}:{branch.kiosk_key}:{window}")
    return hmac.new(settings.SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def current_window(org: Organisation, now: float | None = None) -> int:
    return int((now or time.time()) // max(org.qr_rotation_seconds, 10))


FIXED = "f"  # in place of a time window: the code doesn't change (refresh switched off)


def make_token(org: Organisation, branch: Branch | None = None) -> tuple[str, int | None]:
    """Returns (token, seconds_until_rotation). Branch reception screens get their own codes.
    With refresh off the code is fixed (None seconds) until refresh is switched back on or the
    reception link is changed."""
    who = f"{org.id}" if branch is None else f"{org.id}-{branch.id}"
    if not org.qr_rotate:
        return f"{who}.{FIXED}.{_sign(org, FIXED, branch)}", None
    now = time.time()
    rot = max(org.qr_rotation_seconds, 10)
    w = current_window(org, now)
    remaining = int(rot - (now % rot))
    return f"{who}.{w}.{_sign(org, w, branch)}", remaining


def parse_token(token: str) -> tuple[Organisation | None, Branch | None]:
    """(organisation, branch or None) for a valid token, else (None, None). A token is valid for
    its own window and the one after it (so a scan that starts just before rotation still
    succeeds). Screenshots of the QR expire within about a minute."""
    try:
        who, w, sig = token.strip().split(".")
        org_id, _, branch_id = who.partition("-")
        org = Organisation.objects.get(pk=int(org_id))
        branch = org.branches.get(pk=int(branch_id), is_active=True) if branch_id else None
        if w == FIXED:
            ok = not org.qr_rotate and hmac.compare_digest(sig, _sign(org, FIXED, branch))
            return (org, branch) if ok else (None, None)
        w = int(w)
    except (ValueError, Organisation.DoesNotExist, Branch.DoesNotExist):
        return None, None
    now_w = current_window(org)
    if w not in (now_w, now_w - 1) or not hmac.compare_digest(sig, _sign(org, w, branch)):
        return None, None
    return org, branch


def verify_token(token: str) -> Organisation | None:
    return parse_token(token)[0]


def scan_url(request, token: str) -> str:
    base = settings.ATTENDPRO_PUBLIC_URL or request.build_absolute_uri("/").rstrip("/")
    return f"{base}/scan/?t={token}"


def extract_token(raw: str) -> str:
    """Accepts either a bare token or the full scan URL encoded in the QR."""
    raw = (raw or "").strip()
    if "t=" in raw:
        raw = raw.split("t=", 1)[1].split("&", 1)[0]
    return raw


# --------------------------------------------------------------------------- #
# Marking attendance
# --------------------------------------------------------------------------- #
def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


class ScanResult:
    def __init__(self, ok, action, title, message, record=None):
        self.ok, self.action, self.title, self.message, self.record = ok, action, title, message, record

    def as_dict(self):
        r = self.record
        return {
            "ok": self.ok,
            "action": self.action,
            "title": self.title,
            "message": self.message,
            "check_in": timezone.localtime(r.check_in).strftime("%I:%M %p") if r and r.check_in else None,
            "check_out": timezone.localtime(r.check_out).strftime("%I:%M %p") if r and r.check_out else None,
            "status": r.get_status_display() if r else None,
            "worked": r.worked_display if r else None,
        }


def check_in_closed(org: Organisation, local_now: datetime) -> bool:
    """True from the work end time until midnight. Skipped for overnight shifts (end before start)."""
    return org.work_end > org.work_start and local_now.time() >= org.work_end


def mark_attendance(user: User, token: str, request, verified_org: Organisation | None = None,
                    location: dict | None = None, verified_branch: Branch | None = None,
                    selfie: str | None = None) -> ScanResult:
    """A QR scan (in-page scanner, phone camera link, or a scan held during sign-in). With
    geofencing, the phone's location must also be inside the scanned site's radius."""
    ip = client_ip(request)
    ua = request.META.get("HTTP_USER_AGENT", "")[:255]

    if verified_org is not None:
        org, branch = verified_org, verified_branch
    else:
        org, branch = parse_token(extract_token(token))
    if org is None or org.id != user.organisation_id:
        if user.organisation_id:
            ScanLog.objects.create(organisation_id=user.organisation_id, user=user, action="rejected",
                                   message="Invalid or expired QR code", ip=ip, user_agent=ua)
        return ScanResult(False, "rejected", "QR code not accepted",
                          "This code has expired or belongs to another organisation. "
                          "Scan the live code on the reception screen again.")
    if not org.has_feature(catalog.QR_ATTENDANCE):
        ScanLog.objects.create(organisation=org, user=user, action="rejected",
                               message="QR attendance not in plan", ip=ip, user_agent=ua)
        return ScanResult(False, "rejected", "QR attendance is not available",
                          "Your organisation's plan doesn't include QR attendance. "
                          "Use the Clock in button on your home page instead.")
    if not org.uses_qr:
        ScanLog.objects.create(organisation=org, user=user, action="rejected",
                               message="QR attendance switched off", ip=ip, user_agent=ua)
        return ScanResult(False, "rejected", "Use the Clock in button",
                          f"{org.name} records attendance with the Clock in button on your home page, "
                          f"not the QR code.")
    if branch is not None and not org.has_feature(catalog.MULTI_BRANCH):
        branch = None
    log_extra = {"branch": branch}
    if org.has_feature(catalog.GEOFENCING):
        site = branch_site(branch) if branch else main_site(org)
        if site is not None:
            outcome = check_location([site], location or {}, ua)
            log_extra.update(outcome.log)
            if not outcome.ok:
                ScanLog.objects.create(organisation=org, user=user, action="rejected", message=outcome.log_message,
                                       ip=ip, user_agent=ua, **log_extra)
                return ScanResult(False, "rejected", outcome.title, outcome.message)
    refused = face_gate(user, org, request, selfie, log_extra)
    if refused:
        return refused
    return record_attendance(user, org, request, source="qr", log_extra=log_extra, branch=branch)


# Phones report how sure they are of the position; worse than this and we can't tell
# whether someone is inside the premises, so ask them to turn on GPS / move near a window.
# A site with a bigger radius accepts readings up to its radius (see max_accuracy_for): a phone
# that can only get a cell-tower position (often ±500-800 m) can still clock in at a site whose
# administrators chose a 1 km area.
MAX_ACCURACY_M = 300
# Benefit of the doubt given for GPS error, capped so a vague fix can't stretch the radius far.
ACCURACY_ALLOWANCE_CAP_M = 50


def distance_m(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance in metres (haversine)."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Site:
    """A place attendance may be recorded: the organisation's main location or a branch."""
    branch: Branch | None
    name: str
    lat: float
    lng: float
    radius: int


def main_site(org: Organisation) -> Site | None:
    if not org.has_location:
        return None
    return Site(None, org.name, float(org.latitude), float(org.longitude), org.location_radius_m)


def branch_site(branch: Branch | None) -> Site | None:
    if branch is None or not branch.has_location:
        return None
    return Site(branch, branch.name, float(branch.latitude), float(branch.longitude), branch.radius_m)


def allowed_sites(user: User) -> list[Site]:
    """Where `user` may use the clock-in button.
    Geofencing (Enterprise): the main location and every active branch.
    Multiple branches only: the member's own branch (else the main location).
    Otherwise: the organisation's location."""
    org = user.organisation
    multi = org.has_feature(catalog.MULTI_BRANCH)
    if org.has_feature(catalog.GEOFENCING):
        sites = [main_site(org)]
        if multi:
            sites += [branch_site(b) for b in org.branches.filter(is_active=True)]
        return [s for s in sites if s]
    if multi and user.branch_id and user.branch.is_active:
        s = branch_site(user.branch)
        return [s] if s else []
    s = main_site(org)
    return [s] if s else []


@dataclass
class LocationCheck:
    ok: bool
    title: str = ""
    message: str = ""
    log_message: str = ""
    site: Site | None = None
    log: dict | None = None


def max_accuracy_for(site: Site) -> int:
    """The roughest location reading accepted at `site`, in metres."""
    return max(MAX_ACCURACY_M, int(site.radius or 0))


def locate_good_enough(user: User) -> int:
    """For the phone: after a few seconds of waiting for GPS, it may send a reading this precise
    instead of waiting longer (static/js/locate.js `goodEnough`). The server still decides."""
    sites = allowed_sites(user) if user.organisation_id else []
    if not sites:
        return 60
    site = min(sites, key=lambda s: s.radius)
    return int(max(60, min(max_accuracy_for(site), site.radius * 0.6)))


def precise_location_help(user_agent: str = "") -> str:
    """Where to switch on precise location on this person's phone (matches static/js/locate.js)."""
    ua = user_agent or ""
    in_app, android = "AttendProApp/" in ua, "Android" in ua
    ios = any(k in ua for k in ("iPhone", "iPad", "iPod"))
    if in_app and android:
        return ("On your phone: Settings → Apps → AttendPro → Permissions → Location → Allow, and turn on "
                "“Use precise location”. Also turn on Settings → Location → Google Location Accuracy.")
    if in_app and ios:
        return "On your iPhone: Settings → AttendPro → Location → While Using the App, and turn on Precise Location."
    if android:
        return ("On your phone: Settings → Apps → Chrome → Permissions → Location → turn on “Use precise "
                "location”. Also turn on Settings → Location → Google Location Accuracy.")
    if ios:
        return ("On your iPhone: Settings → Privacy & Security → Location Services → Safari Websites → "
                "While Using the App, and turn on Precise Location.")
    return "Turn on GPS / precise location for this browser."


def check_location(sites: list[Site], loc: dict, user_agent: str = "") -> LocationCheck:
    """Is the reported position inside one of `sites`? `loc` = {"lat", "lng", "accuracy"} from the browser."""
    try:
        lat, lng = float(loc.get("lat")), float(loc.get("lng"))
        accuracy = abs(float(loc.get("accuracy") or 0))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180) or math.isnan(accuracy):
            raise ValueError
    except (TypeError, ValueError):
        return LocationCheck(False, "Location needed",
                             "We need your location to confirm you're at work. Allow location access for "
                             "this site and try again.", "No location received", log={})
    dists = sorted(((distance_m(lat, lng, s.lat, s.lng), s) for s in sites), key=lambda x: x[0])
    dist, site = dists[0]
    log = {"latitude": round(lat, 6), "longitude": round(lng, 6), "accuracy_m": min(int(accuracy), 2_000_000),
           "distance_m": min(int(dist), 2_000_000_000), "branch": site.branch}
    if accuracy > max_accuracy_for(site):
        return LocationCheck(False, "Location not precise enough",
                             f"Your phone could only place you within {int(accuracy)} m, which is too rough "
                             f"to confirm you're at work. Turn on Wi-Fi (it helps even without connecting), "
                             f"step outside or near a window for a minute, and try again. "
                             f"{precise_location_help(user_agent)}",
                             f"Location too imprecise (±{int(accuracy)} m)", site, log)
    if dist - min(accuracy, ACCURACY_ALLOWANCE_CAP_M) > site.radius:
        return LocationCheck(False, "You're not at the workplace",
                             f"You are about {_fmt_distance(dist)} from {site.name}. You can only record "
                             f"attendance within {site.radius} m of it.",
                             f"Outside the allowed area ({_fmt_distance(dist)} from {site.name})", site, log)
    return LocationCheck(True, site=site, log=log)


def clock_by_location(user: User, request, lat, lng, accuracy, selfie: str | None = None) -> ScanResult:
    """The clock-in/out button: allowed only within an allowed site's radius."""
    org = user.organisation
    ip = client_ip(request)
    ua = request.META.get("HTTP_USER_AGENT", "")[:255]

    if not org.has_feature(catalog.MANUAL_CLOCK):
        return ScanResult(False, "rejected", "Clock-in button not available",
                          "Your organisation's plan doesn't include the clock-in button.")
    if not org.uses_button:
        return ScanResult(False, "rejected", "Scan the QR code instead",
                          f"{org.name} records attendance with the QR code at reception, not the Clock in button.")
    sites = allowed_sites(user)
    if not sites:
        return ScanResult(False, "rejected", "Location not set up",
                          "Your administrator hasn't set the attendance location yet. Please let them know.")
    outcome = check_location(sites, {"lat": lat, "lng": lng, "accuracy": accuracy}, ua)
    if not outcome.ok:
        if outcome.log:  # we got coordinates: keep the attempt in the audit trail
            ScanLog.objects.create(organisation=org, user=user, action="rejected", message=outcome.log_message,
                                   ip=ip, user_agent=ua, **outcome.log)
        return ScanResult(False, "rejected", "Location not received" if not outcome.log else outcome.title,
                          "We couldn't read your location. Allow location access and try again."
                          if not outcome.log else outcome.message)
    where = f" at {outcome.site.name}" if outcome.site.branch else ""
    refused = face_gate(user, org, request, selfie, outcome.log)
    if refused:
        return refused
    return record_attendance(user, org, request, source="location", log_extra=outcome.log,
                             note=f"{outcome.log['distance_m']} m from the set location{where}",
                             branch=outcome.site.branch)


def _fmt_distance(m):
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{int(m)} m"


def would_check_in(user: User, org: Organisation) -> bool:
    """Would a scan right now be today's check-in (rather than a check-out, repeat or refusal)?"""
    local_now = timezone.localtime()
    rec = AttendanceRecord.objects.filter(user=user, date=local_now.date()).first()
    return (rec is None or rec.check_in is None) and not check_in_closed(org, local_now)


def face_gate(user: User, org: Organisation, request, selfie, log_extra=None) -> ScanResult | None:
    """Enterprise face verification at check-in. Returns a refusal, or None to carry on.
    Without a selfie it asks the browser for one (action "need_selfie"), which then retries."""
    from faces import services as faces
    if not faces.required(org) or not would_check_in(user, org):
        return None
    if not selfie:
        return ScanResult(False, "need_selfie", "Take a selfie",
                          "Your organisation checks your face when you check in.")
    try:
        outcome = faces.verify(user, org, faces.decode(selfie))
    except faces.SelfieError as e:
        return ScanResult(False, "rejected", "Photo not received", str(e))
    if outcome.ok:
        return None
    ScanLog.objects.create(organisation=org, user=user, action="rejected", message=f"Face check: {outcome.title}",
                           ip=client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
                           **(log_extra or {}))
    return ScanResult(False, "rejected", outcome.title, outcome.message)


def record_attendance(user: User, org: Organisation, request, source: str,
                      log_extra: dict | None = None, note: str = "", branch: Branch | None = None) -> ScanResult:
    """First accepted scan of the day = check-in; later scans = check-out."""
    ip = client_ip(request)
    ua = request.META.get("HTTP_USER_AGENT", "")[:255]
    extra = log_extra or {}

    def log(action, message):
        ScanLog.objects.create(organisation=org, user=user, action=action, message=message,
                               ip=ip, user_agent=ua, **extra)

    now = timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()

    with transaction.atomic():
        rec = AttendanceRecord.objects.select_for_update().filter(user=user, date=today).first()
        if (rec is None or rec.check_in is None) and check_in_closed(org, local_now):
            # Check-in closes at work end until midnight; anyone already in can still check out.
            log("rejected", "Check-in closed for today")
            return ScanResult(False, "rejected", "Check-in is closed for today",
                              f"Check-in closed at {org.work_end:%I:%M %p}. "
                              f"You can check in again tomorrow.")

        rec, created = AttendanceRecord.objects.select_for_update().get_or_create(
            user=user, date=today, defaults={"organisation": org})

        if created or rec.check_in is None:
            rec.check_in = now
            rec.check_in_ip = ip
            rec.source = source
            rec.branch = branch
            rec.status = (AttendanceRecord.STATUS_LATE if local_now.time() > org.late_cutoff(today)
                          else AttendanceRecord.STATUS_PRESENT)
            rec.save()
            late = rec.status == AttendanceRecord.STATUS_LATE
            msg = (f"You arrived {rec.late_by_minutes} min after start time." if late
                   else "You're on time. Have a great day!")
            log("check_in", f"{msg} ({note})" if note else msg)
            if late and org.notify_late:
                notify(org, [a for a in admins_of(org) if a != user], f"{user.display_name} arrived late",
                       f"Checked in at {local_now:%I:%M %p}, {rec.late_by_minutes} min after start time.",
                       url=f"/manage/attendance/?date={today}", kind="late", email=False)
            return ScanResult(True, "check_in", f"Checked in at {local_now:%I:%M %p}", msg, rec)

        last = rec.check_out or rec.check_in
        if now - last < timedelta(minutes=org.checkout_gap_minutes):
            log("duplicate", "Scan ignored (too soon)")
            return ScanResult(True, "duplicate", "Already recorded",
                              f"Your last scan was at {timezone.localtime(last):%I:%M %p}. "
                              f"Come back when you are leaving to check out.", rec)

        rec.check_out = now
        rec.check_out_ip = ip
        rec.save()
        msg = f"Time on site today: {rec.worked_display}. See you next time!"
        log("check_out", f"{msg} ({note})" if note else msg)
        return ScanResult(True, "check_out", f"Checked out at {local_now:%I:%M %p}", msg, rec)


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def build_report(org: Organisation, start: date, end: date, members=None):
    """Per-member summary plus a day-by-day matrix for the period."""
    today = timezone.localdate()
    members = list(members if members is not None else
                   org.members.filter(is_active=True).select_related("department"))
    days = list(daterange(start, end))
    counted_days = [d for d in days if org.is_working_day(d) and d <= today]

    records = (AttendanceRecord.objects.filter(organisation=org, date__range=(start, end), user__in=members)
               .select_related("user"))
    by_user = defaultdict(dict)
    for r in records:
        by_user[r.user_id][r.date] = r

    rows = []
    for m in members:
        recs = by_user.get(m.id, {})
        joined = timezone.localdate(m.date_joined)
        expected = [d for d in counted_days if d >= joined]
        present = sum(1 for r in recs.values() if r.status == AttendanceRecord.STATUS_PRESENT)
        late = sum(1 for r in recs.values() if r.status == AttendanceRecord.STATUS_LATE)
        leave = sum(1 for r in recs.values() if r.status == AttendanceRecord.STATUS_LEAVE)
        attended_expected = sum(1 for d in expected if d in recs and recs[d].status != AttendanceRecord.STATUS_ABSENT)
        absent = len(expected) - attended_expected
        hours = sum(r.worked_hours for r in recs.values())
        arrivals = [timezone.localtime(r.check_in) for r in recs.values() if r.check_in]
        if arrivals:
            avg_min = sum(a.hour * 60 + a.minute for a in arrivals) // len(arrivals)
            avg_arrival = f"{datetime(2000, 1, 1, avg_min // 60, avg_min % 60):%I:%M %p}"
        else:
            avg_arrival = "—"
        rate = round((present + late) * 100 / len(expected), 1) if expected else 0

        cells = []
        for d in days:
            r = recs.get(d)
            if r:
                code = {"present": "P", "late": "L", "leave": "E", "absent": "A"}[r.status]
            elif d > today or d < joined:
                code = ""
            elif not org.is_working_day(d):
                code = "–"
            else:
                code = "A"
            cells.append(code)

        rows.append({
            "user": m, "expected": len(expected), "present": present, "late": late, "leave": leave,
            "absent": max(absent, 0), "attended": present + late, "hours": round(hours, 2),
            "avg_arrival": avg_arrival, "rate": rate, "cells": cells, "records": recs,
        })

    totals = {
        "members": len(rows),
        "working_days": len(counted_days),
        "attended": sum(r["attended"] for r in rows),
        "late": sum(r["late"] for r in rows),
        "absent": sum(r["absent"] for r in rows),
        "hours": round(sum(r["hours"] for r in rows), 1),
        "rate": round(sum(r["rate"] for r in rows) / len(rows), 1) if rows else 0,
    }
    return {"rows": rows, "days": days, "totals": totals, "start": start, "end": end}


def _fmt_time(dt):
    return timezone.localtime(dt).strftime("%I:%M %p") if dt else ""


def export_csv(org, report) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"{org.name} — Attendance Summary", f"{report['start']} to {report['end']}"])
    w.writerow([])
    w.writerow(["ID", "Name", "Department", "Designation", "Expected days", "On time", "Late",
                "Excused", "Absent", "Attendance %", "Total hours", "Avg arrival"])
    for r in report["rows"]:
        u = r["user"]
        w.writerow([u.username, u.display_name, u.department or "", u.designation, r["expected"],
                    r["present"], r["late"], r["leave"], r["absent"], r["rate"], r["hours"], r["avg_arrival"]])
    w.writerow([])
    w.writerow(["Daily log"])
    w.writerow(["Date", "ID", "Name", "Check in", "Check out", "Hours", "Status", "Source", "Note"])
    for r in report["rows"]:
        for d, rec in sorted(r["records"].items()):
            w.writerow([d.isoformat(), r["user"].username, r["user"].display_name, _fmt_time(rec.check_in),
                        _fmt_time(rec.check_out), rec.worked_hours or "", rec.get_status_display(),
                        rec.get_source_display(), rec.note])
    return buf.getvalue().encode("utf-8-sig")


def export_xlsx(org, report) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    navy = "1E2A4A"
    header_fill = PatternFill("solid", fgColor=navy)
    header_font = Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="D9DEE8")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    fills = {
        "P": PatternFill("solid", fgColor="D7F5E3"), "L": PatternFill("solid", fgColor="FFF0C7"),
        "A": PatternFill("solid", fgColor="FBD9D9"), "E": PatternFill("solid", fgColor="DCE7FB"),
    }

    def title_block(ws, subtitle):
        ws["A1"] = org.name
        ws["A1"].font = Font(bold=True, size=15, color=navy)
        ws["A2"] = f"{subtitle} · {report['start']:%d %b %Y} – {report['end']:%d %b %Y}"
        ws["A2"].font = Font(size=10, color="6B7280")
        ws["A3"] = f"Generated {timezone.localtime():%d %b %Y, %I:%M %p} · AttendPro by Techmiary"
        ws["A3"].font = Font(size=9, italic=True, color="9CA3AF")

    def header_row(ws, row, headers):
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=row, column=i, value=h)
            c.fill, c.font, c.border = header_fill, header_font, border
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 30

    wb = Workbook()

    # Sheet 1 — summary
    ws = wb.active
    ws.title = "Summary"
    title_block(ws, "Attendance summary")
    headers = ["ID", "Name", "Department", "Designation", "Expected days", "On time", "Late", "Excused",
               "Absent", "Attendance %", "Total hours", "Avg arrival"]
    header_row(ws, 5, headers)
    for i, r in enumerate(report["rows"], 6):
        u = r["user"]
        vals = [u.username, u.display_name, str(u.department or ""), u.designation, r["expected"], r["present"],
                r["late"], r["leave"], r["absent"], r["rate"] / 100, r["hours"], r["avg_arrival"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            c.border = border
            if j >= 5:
                c.alignment = Alignment(horizontal="center")
        ws.cell(row=i, column=10).number_format = "0.0%"
    for j, wdt in enumerate([12, 26, 18, 18, 10, 9, 8, 9, 9, 12, 11, 12], 1):
        ws.column_dimensions[get_column_letter(j)].width = wdt
    ws.freeze_panes = "C6"

    # Sheet 2 — daily register
    ws2 = wb.create_sheet("Daily register")
    title_block(ws2, "Daily register (P on time · L late · A absent · E excused · – non-working day)")
    header_row(ws2, 5, ["ID", "Name"] + [d.strftime("%a\n%d %b") for d in report["days"]] + ["Total"])
    for i, r in enumerate(report["rows"], 6):
        ws2.cell(row=i, column=1, value=r["user"].username).border = border
        ws2.cell(row=i, column=2, value=r["user"].display_name).border = border
        for j, code in enumerate(r["cells"], 3):
            c = ws2.cell(row=i, column=j, value=code)
            c.alignment = Alignment(horizontal="center")
            c.border = border
            if code in fills:
                c.fill = fills[code]
        t = ws2.cell(row=i, column=len(r["cells"]) + 3, value=r["attended"])
        t.font, t.alignment, t.border = Font(bold=True), Alignment(horizontal="center"), border
    ws2.column_dimensions["A"].width = 12
    ws2.column_dimensions["B"].width = 26
    for j in range(3, len(report["days"]) + 4):
        ws2.column_dimensions[get_column_letter(j)].width = 7
    ws2.freeze_panes = "C6"

    # Sheet 3 — detailed log
    ws3 = wb.create_sheet("Time log")
    title_block(ws3, "Check-in / check-out log")
    header_row(ws3, 5, ["Date", "ID", "Name", "Department", "Check in", "Check out", "Hours", "Status",
                        "Source", "Note"])
    row = 6
    entries = sorted(((d, r["user"], rec) for r in report["rows"] for d, rec in r["records"].items()),
                     key=lambda x: (x[0], x[1].username))
    for d, u, rec in entries:
        vals = [d, u.username, u.display_name, str(u.department or ""), _fmt_time(rec.check_in),
                _fmt_time(rec.check_out), rec.worked_hours or None, rec.get_status_display(),
                rec.get_source_display(), rec.note]
        for j, v in enumerate(vals, 1):
            c = ws3.cell(row=row, column=j, value=v)
            c.border = border
        ws3.cell(row=row, column=1).number_format = "DD MMM YYYY"
        row += 1
    for j, wdt in enumerate([13, 12, 26, 18, 11, 11, 8, 18, 12, 30], 1):
        ws3.column_dimensions[get_column_letter(j)].width = wdt
    ws3.freeze_panes = "A6"

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_pdf(org, report) -> bytes:
    """Print-ready report: summary table, then the daily register for periods up to 31 days."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    navy, muted, line = colors.HexColor("#1E2A4A"), colors.HexColor("#6B7280"), colors.HexColor("#D9DEE8")
    zebra = colors.HexColor("#F6F8FC")
    fills = {"P": "#D7F5E3", "L": "#FFF0C7", "A": "#FBD9D9", "E": "#DCE7FB"}
    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=navy, spaceAfter=2)
    sub = ParagraphStyle("s", fontName="Helvetica", fontSize=9, leading=12, textColor=muted, spaceAfter=10)
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=8, leading=10)
    generated = f"Generated {timezone.localtime():%d %b %Y, %I:%M %p} · AttendPro by Techmiary"

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(12 * mm, 8 * mm, f"{org.name} · {generated}")
        canvas.drawRightString(doc.pagesize[0] - 12 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    def base_style(n_rows):
        style = [("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                 ("GRID", (0, 0), (-1, -1), 0.4, line), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        style += [("BACKGROUND", (0, i), (-1, i), zebra) for i in range(2, n_rows, 2)]
        return style

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm, title=f"{org.name} attendance report")
    t = report["totals"]
    story = [Paragraph(f"{org.name} — Attendance report", title),
             Paragraph(f"{report['start']:%d %b %Y} – {report['end']:%d %b %Y} · {t['members']} members · "
                       f"{t['working_days']} working days · average attendance {t['rate']}% · "
                       f"{t['late']} late arrivals · {t['absent']} absences · {t['hours']} hours", sub)]

    head = ["ID", "Name", "Department", "Expected", "On time", "Late", "Excused", "Absent", "Attendance",
            "Hours", "Avg arrival"]
    rows = [head] + [[r["user"].username, Paragraph(r["user"].display_name, cell),
                      Paragraph(str(r["user"].department or "—"), cell), r["expected"], r["present"], r["late"],
                      r["leave"], r["absent"], f"{r['rate']}%", r["hours"], r["avg_arrival"]]
                     for r in report["rows"]]
    summary = Table(rows, repeatRows=1, colWidths=[22 * mm, 55 * mm, 40 * mm] + [19 * mm] * 5 + [22 * mm, 17 * mm, 22 * mm])
    style = base_style(len(rows)) + [("ALIGN", (3, 1), (-1, -1), "CENTER")]
    for i, r in enumerate(report["rows"], 1):
        if r["rate"] < 75 and r["expected"]:
            style.append(("TEXTCOLOR", (8, i), (8, i), colors.HexColor("#C0392B")))
    summary.setStyle(TableStyle(style))
    story.append(summary)

    days = report["days"]
    if report["rows"] and len(days) <= 31:
        story += [PageBreak(), Paragraph("Daily register", title),
                  Paragraph("P on time · L late · A absent · E excused / leave · – non-working day", sub)]
        head = ["Name"] + [f"{d:%d}\n{d:%a}"[:6] for d in days] + ["Total"]
        reg = [head] + [[Paragraph(r["user"].display_name, cell)] + r["cells"] + [r["attended"]]
                        for r in report["rows"]]
        day_w = min(7.5 * mm, (273 * mm - 50 * mm - 12 * mm) / len(days))
        table = Table(reg, repeatRows=1, colWidths=[50 * mm] + [day_w] * len(days) + [12 * mm])
        style = base_style(len(reg)) + [("ALIGN", (1, 0), (-1, -1), "CENTER"), ("FONTSIZE", (1, 0), (-1, 0), 6.5)]
        for i, r in enumerate(report["rows"], 1):
            for j, code in enumerate(r["cells"], 1):
                if code in fills:
                    style.append(("BACKGROUND", (j, i), (j, i), colors.HexColor(fills[code])))
        table.setStyle(TableStyle(style))
        story.append(table)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
