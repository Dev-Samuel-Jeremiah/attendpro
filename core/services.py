"""Business logic: rotating QR tokens, marking attendance, and reports."""
import csv
import hashlib
import hmac
import io
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import AttendanceRecord, Organisation, ScanLog, User


# --------------------------------------------------------------------------- #
# Rotating QR tokens
# --------------------------------------------------------------------------- #
def _sign(org: Organisation, window: int) -> str:
    msg = f"{org.id}:{org.kiosk_key}:{window}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:16]


def current_window(org: Organisation, now: float | None = None) -> int:
    return int((now or time.time()) // max(org.qr_rotation_seconds, 10))


def make_token(org: Organisation) -> tuple[str, int]:
    """Returns (token, seconds_until_rotation)."""
    now = time.time()
    rot = max(org.qr_rotation_seconds, 10)
    w = current_window(org, now)
    remaining = int(rot - (now % rot))
    return f"{org.id}.{w}.{_sign(org, w)}", remaining


def verify_token(token: str) -> Organisation | None:
    """A token is valid for its own window and the one after it (so a scan
    that starts just before rotation still succeeds). Screenshots of the QR
    expire within about a minute."""
    try:
        org_id, w, sig = token.strip().split(".")
        org = Organisation.objects.get(pk=int(org_id))
        w = int(w)
    except (ValueError, Organisation.DoesNotExist):
        return None
    now_w = current_window(org)
    if w not in (now_w, now_w - 1):
        return None
    if not hmac.compare_digest(sig, _sign(org, w)):
        return None
    return org


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


def mark_attendance(user: User, token: str, request, verified_org: Organisation | None = None) -> ScanResult:
    ip = client_ip(request)
    ua = request.META.get("HTTP_USER_AGENT", "")[:255]

    org = verified_org or verify_token(extract_token(token))
    if org is None or org.id != user.organisation_id:
        if user.organisation_id:
            ScanLog.objects.create(organisation_id=user.organisation_id, user=user, action="rejected",
                                   message="Invalid or expired QR code", ip=ip, user_agent=ua)
        return ScanResult(False, "rejected", "QR code not accepted",
                          "This code has expired or belongs to another organisation. "
                          "Scan the live code on the reception screen again.")

    now = timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()

    with transaction.atomic():
        rec = AttendanceRecord.objects.select_for_update().filter(user=user, date=today).first()
        if (rec is None or rec.check_in is None) and check_in_closed(org, local_now):
            # Check-in closes at work end until midnight; anyone already in can still check out.
            ScanLog.objects.create(organisation=org, user=user, action="rejected",
                                   message="Check-in closed for today", ip=ip, user_agent=ua)
            return ScanResult(False, "rejected", "Check-in is closed for today",
                              f"Check-in closed at {org.work_end:%I:%M %p}. "
                              f"You can check in again tomorrow.")

        rec, created = AttendanceRecord.objects.select_for_update().get_or_create(
            user=user, date=today, defaults={"organisation": org})

        if created or rec.check_in is None:
            rec.check_in = now
            rec.check_in_ip = ip
            rec.source = "qr"
            rec.status = (AttendanceRecord.STATUS_LATE if local_now.time() > org.late_cutoff(today)
                          else AttendanceRecord.STATUS_PRESENT)
            rec.save()
            late = rec.status == AttendanceRecord.STATUS_LATE
            msg = (f"You arrived {rec.late_by_minutes} min after start time." if late
                   else "You're on time. Have a great day!")
            ScanLog.objects.create(organisation=org, user=user, action="check_in", message=msg, ip=ip, user_agent=ua)
            return ScanResult(True, "check_in", f"Checked in at {local_now:%I:%M %p}", msg, rec)

        last = rec.check_out or rec.check_in
        if now - last < timedelta(minutes=org.checkout_gap_minutes):
            ScanLog.objects.create(organisation=org, user=user, action="duplicate",
                                   message="Scan ignored (too soon)", ip=ip, user_agent=ua)
            return ScanResult(True, "duplicate", "Already recorded",
                              f"Your last scan was at {timezone.localtime(last):%I:%M %p}. "
                              f"Scan again when you are leaving to check out.", rec)

        rec.check_out = now
        rec.check_out_ip = ip
        rec.save()
        msg = f"Time on site today: {rec.worked_display}. See you next time!"
        ScanLog.objects.create(organisation=org, user=user, action="check_out", message=msg, ip=ip, user_agent=ua)
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
