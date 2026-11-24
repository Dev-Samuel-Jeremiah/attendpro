"""Organisation backups (a ZIP of CSV files) and the 30-day "recently deleted" bin."""
import csv
import io
import zipfile
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from billing import catalog

from .models import DeletedItem, OrgBackup

KEEP_AUTOMATIC = 8          # weekly backups kept
KEEP_DELETED_DAYS = 30


class RestoreError(ValueError):
    pass


def enabled(org):
    return org.has_feature(catalog.BACKUP)


# --------------------------------------------------------------------------- #
# Full export
# --------------------------------------------------------------------------- #
def _csv(rows, header):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _t(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M") if dt else ""


def export_zip(org) -> bytes:
    from core.models import AttendanceRecord, ScanLog
    from leave.models import LeaveRequest
    from payroll.models import PayrollLine

    files = {
        "members.csv": _csv([[u.username, u.first_name, u.last_name, u.get_role_display(), u.get_category_display(),
                              u.department or "", u.branch or "", u.designation, u.email, u.phone,
                              "yes" if u.is_active else "no", _t(u.date_joined)]
                             for u in org.members.select_related("department", "branch").order_by("username")],
                            ["ID", "First name", "Last name", "Access", "Category", "Department", "Branch",
                             "Job title / class", "Email", "Phone", "Active", "Joined"]),
        "departments.csv": _csv([[d.name] for d in org.departments.all()], ["Name"]),
        "branches.csv": _csv([[b.name, b.address, b.latitude or "", b.longitude or "", b.radius_m,
                               "yes" if b.is_active else "no"] for b in org.branches.all()],
                             ["Name", "Address", "Latitude", "Longitude", "Radius (m)", "Active"]),
        "attendance.csv": _csv([[r.date, r.user.username, r.user.display_name, _t(r.check_in), _t(r.check_out),
                                 r.worked_hours or "", r.get_status_display(), r.get_source_display(),
                                 r.branch or "", r.note]
                                for r in AttendanceRecord.objects.filter(organisation=org)
                                .select_related("user", "branch").order_by("date", "user__username")],
                               ["Date", "ID", "Name", "Check in", "Check out", "Hours", "Status", "Source",
                                "Branch", "Note"]),
        "leave.csv": _csv([[l.user.username, l.user.display_name, l.leave_type.name, l.start_date, l.end_date, l.days,
                            l.get_status_display(), l.reason, l.review_note]
                           for l in LeaveRequest.objects.filter(organisation=org).select_related("user", "leave_type")],
                          ["ID", "Name", "Type", "From", "To", "Working days", "Status", "Reason", "Decision note"]),
        "scan-log.csv": _csv([[_t(s.timestamp), s.user.username, s.action, s.message, s.ip or "", s.distance_m or ""]
                              for s in ScanLog.objects.filter(organisation=org,
                                                              timestamp__gte=timezone.now() - timedelta(days=366))
                              .select_related("user").order_by("timestamp")],
                             ["Time", "ID", "Result", "Detail", "IP address", "Distance (m)"]),
        "payroll.csv": _csv([[l.run.month.strftime("%Y-%m"), l.run.get_status_display(), l.user.username,
                              l.user.display_name, l.gross, l.late_deduction, l.absence_deduction, l.adjustment, l.net]
                             for l in PayrollLine.objects.filter(run__organisation=org).select_related("run", "user")],
                            ["Month", "Status", "ID", "Name", "Gross", "Late deduction", "Absence deduction",
                             "Adjustment", "Net"]),
    }
    readme = (f"AttendPro backup of {org.name} ({org.code})\nMade {_t(timezone.now())}\n\n"
              "Each CSV opens in Excel or Google Sheets. Keep this file somewhere safe.\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", readme)
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def make_backup(org, kind=OrgBackup.AUTO, by=None) -> OrgBackup:
    data = export_zip(org)
    backup = OrgBackup(organisation=org, kind=kind, created_by=by, size=len(data))
    backup.file.save(f"{org.code}-{timezone.localtime():%Y%m%d-%H%M}.zip", ContentFile(data), save=False)
    backup.save()
    old = org.backups.filter(kind=OrgBackup.AUTO)[KEEP_AUTOMATIC:] if kind == OrgBackup.AUTO else []
    for b in old:
        delete_backup(b)
    return backup


def delete_backup(backup):
    if backup.file:
        backup.file.delete(save=False)
    backup.delete()


def weekly_backups(now=None):
    """Called by the scheduled alerts job: one automatic backup a week per Enterprise organisation."""
    from core.models import Organisation
    now = now or timezone.now()
    made = []
    for org in Organisation.objects.select_related("plan"):
        if not enabled(org):
            continue
        last = org.backups.filter(kind=OrgBackup.AUTO).first()
        if last is None or now - last.created_at >= timedelta(days=7):
            make_backup(org)
            made.append(org.code)
    return made


# --------------------------------------------------------------------------- #
# Recently deleted
# --------------------------------------------------------------------------- #
def _iso(v):
    return v.isoformat() if v else None


def trash(obj, by):
    """Delete `obj`, keeping a copy for 30 days when the plan includes recovery."""
    from core.models import AttendanceRecord, Branch, Department
    org = obj.organisation
    if enabled(org):
        if isinstance(obj, AttendanceRecord):
            kind, label = DeletedItem.ATTENDANCE, f"{obj.user.display_name} · {obj.date:%d %b %Y}"
            payload = {"user": obj.user_id, "date": obj.date.isoformat(), "check_in": _iso(obj.check_in),
                       "check_out": _iso(obj.check_out), "status": obj.status, "source": obj.source, "note": obj.note,
                       "branch": obj.branch_id, "leave_request": obj.leave_request_id}
        elif isinstance(obj, Department):
            kind, label = DeletedItem.DEPARTMENT, obj.name
            payload = {"name": obj.name, "members": list(obj.members.values_list("id", flat=True))}
        elif isinstance(obj, Branch):
            kind, label = DeletedItem.BRANCH, obj.name
            payload = {"name": obj.name, "address": obj.address, "latitude": str(obj.latitude or ""),
                       "longitude": str(obj.longitude or ""), "radius_m": obj.radius_m, "is_active": obj.is_active,
                       "members": list(obj.members.values_list("id", flat=True))}
        else:
            raise TypeError(f"Can't keep a copy of {type(obj).__name__}")
        DeletedItem.objects.create(organisation=org, kind=kind, label=label, payload=payload, deleted_by=by)
    obj.delete()


@transaction.atomic
def restore(item, by=None):
    from core.models import AttendanceRecord, Branch, Department
    if item.restored_at:
        raise RestoreError("That has already been restored.")
    org, p = item.organisation, item.payload
    if item.kind == DeletedItem.ATTENDANCE:
        user = org.members.filter(pk=p["user"]).first()
        if user is None:
            raise RestoreError("That person no longer exists.")
        day = parse_date(p["date"])
        if AttendanceRecord.objects.filter(user=user, date=day).exists():
            raise RestoreError(f"{user.display_name} already has an entry for {day:%d %b %Y}. Delete it first.")
        AttendanceRecord.objects.create(
            organisation=org, user=user, date=day, status=p["status"], source=p["source"], note=p["note"],
            check_in=parse_datetime(p["check_in"]) if p["check_in"] else None,
            check_out=parse_datetime(p["check_out"]) if p["check_out"] else None,
            branch=org.branches.filter(pk=p.get("branch")).first() if p.get("branch") else None,
            leave_request_id=p.get("leave_request") if p.get("leave_request") and
            org.leave_requests.filter(pk=p["leave_request"]).exists() else None)
    elif item.kind == DeletedItem.DEPARTMENT:
        if org.departments.filter(name__iexact=p["name"]).exists():
            raise RestoreError(f"A department called “{p['name']}” already exists.")
        dept = Department.objects.create(organisation=org, name=p["name"])
        org.members.filter(pk__in=p["members"], department__isnull=True).update(department=dept)
    elif item.kind == DeletedItem.BRANCH:
        if org.branches.filter(name__iexact=p["name"]).exists():
            raise RestoreError(f"A branch called “{p['name']}” already exists.")
        branch = Branch.objects.create(organisation=org, name=p["name"], address=p["address"],
                                       latitude=p["latitude"] or None, longitude=p["longitude"] or None,
                                       radius_m=p["radius_m"], is_active=p["is_active"])
        org.members.filter(pk__in=p["members"], branch__isnull=True).update(branch=branch)
    item.restored_at = timezone.now()
    item.save(update_fields=["restored_at"])
    return item


def purge_deleted(now=None):
    cutoff = (now or timezone.now()) - timedelta(days=KEEP_DELETED_DAYS)
    return DeletedItem.objects.filter(deleted_at__lt=cutoff).delete()[0]
