import csv
import io
import json
import secrets
from datetime import date, timedelta

import qrcode
import qrcode.image.svg
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from billing import catalog
from billing.services import feature_required, staff_limit_message, upgrade_message

from . import services
from .decorators import member_required, org_admin_required
from .forms import (ChangePasswordForm, DepartmentForm, ImportForm, LoginForm, MemberForm,
                    OrgRegisterForm, OrgSettingsForm, RecordForm)
from .models import AttendanceRecord, Department, Organisation, SavedReport, ScanLog, User


def _gen_password():
    # Easy to read aloud / type on a phone: no 0/O/1/l
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _parse_date(s, default):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return default


# =========================================================================== #
# Auth
# =========================================================================== #
def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    nxt = request.GET.get("next") or request.POST.get("next") or ""
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.user)
        if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
            return redirect(nxt)
        return redirect("home")
    return render(request, "auth/login.html", {"form": form, "next": nxt,
                                               "scan_pending": "/scan/" in nxt})


def logout_view(request):
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("login")


def register_org(request):
    form = OrgRegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        with transaction.atomic():
            org = Organisation.objects.create(name=cd["org_name"], code=cd["code"], org_type=cd["org_type"],
                                              email=cd["email"])
            admin = User.objects.create_user(
                username=org.next_member_id(), password=cd["password1"], first_name=cd["first_name"],
                last_name=cd["last_name"], email=cd["email"], organisation=org, role=User.ROLE_ADMIN,
                designation="Administrator")
        login(request, admin)
        messages.success(request, f"Welcome! Your admin ID is {admin.username} — use it to sign in next time.")
        return redirect("dashboard")
    return render(request, "auth/register.html", {"form": form})


def home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if request.user.is_superuser and not request.user.organisation_id:
        return redirect("platform")
    return _member_home(request)


@member_required
def _member_home(request):
    return redirect("dashboard" if request.user.is_org_admin else "portal")


# =========================================================================== #
# Scanning
# =========================================================================== #
PENDING_SCAN_SECONDS = 180


def scan(request):
    """Target of the QR URL. Phone camera → opens this → attendance marked.

    If the person is not signed in yet, the QR is verified *now* and remembered
    for a few minutes, so the scan still counts after they log in even though
    the code on screen has rotated in the meantime."""
    token = request.GET.get("t", "")
    if not request.user.is_authenticated:
        org = services.verify_token(token) if token else None
        if org:
            request.session["pending_scan"] = {"org": org.id, "at": timezone.now().timestamp()}
            messages.info(request, "Sign in to complete your attendance scan.")
        else:
            messages.error(request, "That QR code has expired. Sign in, then scan the live code again.")
        return redirect(f"{reverse('login')}?next={reverse('scan')}")
    if not request.user.organisation_id:
        return redirect("login")

    result = None
    pending = request.session.pop("pending_scan", None)
    if token:
        result = services.mark_attendance(request.user, token, request)
    elif pending and timezone.now().timestamp() - pending["at"] < PENDING_SCAN_SECONDS \
            and pending["org"] == request.user.organisation_id:
        result = services.mark_attendance(request.user, "", request, verified_org=request.user.organisation)
    return render(request, "staff/scan_result.html", {"result": result})


@member_required
@require_POST
def api_scan(request):
    try:
        token = json.loads(request.body or "{}").get("token", "")
    except json.JSONDecodeError:
        token = request.POST.get("token", "")
    return JsonResponse(services.mark_attendance(request.user, token, request).as_dict())


@member_required
def scanner(request):
    if not request.user.organisation.has_feature(catalog.QR_ATTENDANCE):
        messages.info(request, upgrade_message(catalog.QR_ATTENDANCE) if request.user.is_org_admin
                      else "Use the Clock in button to record your attendance.")
        return redirect("billing" if request.user.is_org_admin else "portal")
    return render(request, "staff/scanner.html")


@member_required
@require_POST
def api_clock(request):
    """Clock-in/out button. Body: {"lat": .., "lng": .., "accuracy": ..} from the browser."""
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        data = {}
    result = services.clock_by_location(request.user, request, data.get("lat"), data.get("lng"),
                                        data.get("accuracy"))
    return JsonResponse(result.as_dict())


# =========================================================================== #
# Reception kiosk (public URL protected by secret key)
# =========================================================================== #
def kiosk(request, key):
    org = get_object_or_404(Organisation, kiosk_key=key)
    return render(request, "kiosk/display.html", {
        "kiosk_org": org, "key": key, "qr_allowed": org.has_feature(catalog.QR_ATTENDANCE),
        "show_logo": org.has_feature(catalog.CUSTOM_BRANDING)})


def kiosk_token(request, key):
    org = get_object_or_404(Organisation, kiosk_key=key)
    if not org.has_feature(catalog.QR_ATTENDANCE):
        return JsonResponse({"error": "QR attendance is not included in this plan."}, status=403)
    token, remaining = services.make_token(org)
    url = services.scan_url(request, token)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=1,
                       image_factory=qrcode.image.svg.SvgPathImage)
    qr.add_data(url)
    qr.make(fit=True)
    svg = qr.make_image().to_string(encoding="unicode")

    today = timezone.localdate()
    recent = (ScanLog.objects.filter(organisation=org, timestamp__date=today,
                                     action__in=["check_in", "check_out"])
              .select_related("user")[:6])
    present = AttendanceRecord.objects.filter(organisation=org, date=today, check_in__isnull=False).count()
    total = org.members.filter(is_active=True).count()
    resp = JsonResponse({
        "svg": svg, "remaining": remaining, "rotation": org.qr_rotation_seconds,
        "present": present, "total": total,
        "recent": [{"name": l.user.first_name or l.user.username, "initials": l.user.initials,
                    "action": "In" if l.action == "check_in" else "Out",
                    "time": timezone.localtime(l.timestamp).strftime("%I:%M %p")} for l in recent],
    })
    resp["Cache-Control"] = "no-store"
    return resp


# =========================================================================== #
# Staff / student portal
# =========================================================================== #
@member_required
def portal(request):
    u, org = request.user, request.user.organisation
    today = timezone.localdate()
    rec = AttendanceRecord.objects.filter(user=u, date=today).first()
    month_start = today.replace(day=1)
    report = services.build_report(org, month_start, today, members=[u])
    summary = report["rows"][0]
    recent = AttendanceRecord.objects.filter(user=u).order_by("-date")[:7]
    return render(request, "staff/portal.html", {
        "rec": rec, "summary": summary, "recent": recent, "today": today,
        "is_working_day": org.is_working_day(today),
        "closed": (not rec or not rec.check_in) and services.check_in_closed(org, timezone.localtime()),
    })


@member_required
def my_history(request):
    u, org = request.user, request.user.organisation
    today = timezone.localdate()
    start = _parse_date(request.GET.get("start"), today.replace(day=1))
    end = _parse_date(request.GET.get("end"), today)
    report = services.build_report(org, start, end, members=[u])
    row = report["rows"][0]
    days = []
    for d, code in zip(report["days"], row["cells"]):
        days.append({"date": d, "code": code, "rec": row["records"].get(d)})
    days.reverse()
    if request.GET.get("export") == "csv":
        if not org.has_feature(catalog.SELF_SERVICE):
            messages.info(request, "Downloading your history isn't included in your organisation's plan.")
            return redirect("my_history")
        resp = HttpResponse(services.export_csv(org, report), content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="my-attendance-{start}-{end}.csv"'
        return resp
    return render(request, "staff/history.html", {"row": row, "days": days, "start": start, "end": end})


@member_required
def change_password(request):
    form = ChangePasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.set_password(form.cleaned_data["new1"])
        request.user.save()
        update_session_auth_hash(request, request.user)
        messages.success(request, "Password updated.")
        return redirect("home")
    return render(request, "staff/password.html", {"form": form})


# =========================================================================== #
# Admin: dashboard
# =========================================================================== #
@org_admin_required
def dashboard(request):
    org = request.user.organisation
    today = timezone.localdate()
    members = org.members.filter(is_active=True)
    total = members.count()
    recs = AttendanceRecord.objects.filter(organisation=org, date=today).select_related("user", "user__department")
    present = recs.filter(status__in=["present", "late"]).count()
    late = recs.filter(status="late").count()
    leave = recs.filter(status="leave").count()
    on_site = recs.filter(check_in__isnull=False, check_out__isnull=True).count()
    absent_members = members.exclude(attendance__date=today).select_related("department")[:50]

    # 14-day trend
    trend = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        agg = AttendanceRecord.objects.filter(organisation=org, date=d).aggregate(
            on_time=Count("id", filter=Q(status="present")), late=Count("id", filter=Q(status="late")))
        trend.append({"date": d, "on_time": agg["on_time"], "late": agg["late"],
                      "working": org.is_working_day(d)})
    peak = max([t["on_time"] + t["late"] for t in trend] + [total, 1])
    for t in trend:
        t["on_time_pct"] = round(t["on_time"] * 100 / peak, 1)
        t["late_pct"] = round(t["late"] * 100 / peak, 1)

    # Department breakdown today
    depts = []
    for dpt in org.departments.annotate(n=Count("members", filter=Q(members__is_active=True))):
        p = recs.filter(user__department=dpt, status__in=["present", "late"]).count()
        depts.append({"name": dpt.name, "total": dpt.n, "present": p,
                      "pct": round(p * 100 / dpt.n) if dpt.n else 0})

    return render(request, "manage/dashboard.html", {
        "today": today, "total": total, "present": present, "late": late, "leave": leave,
        "absent": max(total - present - leave, 0), "on_site": on_site,
        "rate": round(present * 100 / total) if total else 0,
        "recs": recs.order_by("-check_in")[:12], "absent_members": absent_members,
        "trend": trend, "depts": depts, "is_working_day": org.is_working_day(today),
    })


@org_admin_required
def live_feed(request):
    org = request.user.organisation
    today = timezone.localdate()
    logs = ScanLog.objects.filter(organisation=org, timestamp__date=today).select_related("user")[:15]
    return JsonResponse({"logs": [{
        "name": l.user.display_name, "id": l.user.username, "initials": l.user.initials,
        "action": l.action, "time": timezone.localtime(l.timestamp).strftime("%I:%M:%S %p"),
        "message": l.message} for l in logs],
        "present": AttendanceRecord.objects.filter(organisation=org, date=today,
                                                   status__in=["present", "late"]).count()})


# =========================================================================== #
# Admin: members
# =========================================================================== #
@org_admin_required
def members(request):
    org = request.user.organisation
    qs = org.members.select_related("department")
    q = request.GET.get("q", "").strip()
    dept = request.GET.get("dept", "")
    status = request.GET.get("status", "active")
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q) |
                       Q(email__icontains=q) | Q(designation__icontains=q))
    if dept:
        qs = qs.filter(department_id=dept)
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    today = timezone.localdate()
    today_recs = {r.user_id: r for r in AttendanceRecord.objects.filter(organisation=org, date=today)}
    rows = [(m, today_recs.get(m.id)) for m in qs]
    return render(request, "manage/members.html", {
        "rows": rows, "q": q, "dept": dept, "status": status, "departments": org.departments.all(),
        "dept_form": DepartmentForm()})


@org_admin_required
def member_add(request):
    org = request.user.organisation
    if org.seats_left() == 0:
        messages.warning(request, staff_limit_message(org))
        return redirect("billing")
    form = MemberForm(org, request.POST or None, request.FILES or None, initial={"is_active": True})
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data.get("is_active") and org.seats_left() == 0:
            messages.warning(request, staff_limit_message(org))
            return redirect("billing")
        m = form.save(commit=False)
        m.organisation = org
        m.username = org.next_member_id()
        pwd = form.cleaned_data.get("password") or _gen_password()
        m.set_password(pwd)
        m.save()
        request.session["new_credentials"] = [{"id": m.username, "name": m.display_name, "password": pwd}]
        return redirect("credentials")
    return render(request, "manage/member_form.html", {"form": form, "title": "Register member"})


@org_admin_required
def member_edit(request, pk):
    org = request.user.organisation
    m = get_object_or_404(User, pk=pk, organisation=org)
    form = MemberForm(org, request.POST or None, request.FILES or None, instance=m)
    if request.method == "POST" and form.is_valid():
        reactivating = form.cleaned_data["is_active"] and not User.objects.get(pk=m.pk).is_active
        if m == request.user and (form.cleaned_data["role"] != User.ROLE_ADMIN or not form.cleaned_data["is_active"]):
            messages.error(request, "You cannot remove your own admin access or deactivate yourself.")
        elif reactivating and org.seats_left() == 0:
            messages.error(request, staff_limit_message(org))
        else:
            m = form.save(commit=False)
            if form.cleaned_data.get("password"):
                m.set_password(form.cleaned_data["password"])
            m.save()
            messages.success(request, f"{m.display_name} updated.")
            return redirect("members")
    recent = m.attendance.order_by("-date")[:10]
    return render(request, "manage/member_form.html", {"form": form, "member": m, "recent": recent,
                                                       "title": f"Edit {m.display_name}"})


@org_admin_required
@require_POST
def member_reset_password(request, pk):
    m = get_object_or_404(User, pk=pk, organisation=request.user.organisation)
    pwd = _gen_password()
    m.set_password(pwd)
    m.save()
    request.session["new_credentials"] = [{"id": m.username, "name": m.display_name, "password": pwd}]
    return redirect("credentials")


@org_admin_required
def credentials(request):
    creds = request.session.pop("new_credentials", None)
    if not creds:
        return redirect("members")
    return render(request, "manage/credentials.html", {"creds": creds,
                                                       "login_url": request.build_absolute_uri(reverse("login"))})


@org_admin_required
def member_import(request):
    org = request.user.organisation
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        raw = form.cleaned_data["file"].read().decode("utf-8-sig", errors="ignore")
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(io.StringIO(raw))]
        skipped = sum(1 for row in rows if not row.get("first_name"))
        rows = [row for row in rows if row.get("first_name")]
        left = org.seats_left()
        if left is not None and len(rows) > left:
            messages.error(request, f"This file has {len(rows)} members but your plan has room for {left} more. "
                                    + staff_limit_message(org))
            return render(request, "manage/import.html", {"form": form})
        creds = []
        with transaction.atomic():
            for row in rows:
                dept = None
                if row.get("department"):
                    dept, _ = Department.objects.get_or_create(organisation=org, name=row["department"])
                pwd = _gen_password()
                m = User(organisation=org, username=org.next_member_id(), first_name=row["first_name"],
                         last_name=row.get("last_name", ""), email=row.get("email", ""),
                         phone=row.get("phone", ""), designation=row.get("designation", ""), department=dept,
                         category="student" if row.get("category", "").lower().startswith("stud") else "staff")
                m.set_password(pwd)
                m.save()
                creds.append({"id": m.username, "name": m.display_name, "password": pwd})
        if skipped:
            messages.warning(request, f"{skipped} row(s) skipped because first_name was empty.")
        if creds:
            request.session["new_credentials"] = creds
            return redirect("credentials")
        messages.error(request, "No members found in that file.")
    return render(request, "manage/import.html", {"form": form})


@org_admin_required
def import_template(request):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="attendpro-members-template.csv"'
    w = csv.writer(resp)
    w.writerow(["first_name", "last_name", "category", "department", "designation", "email", "phone"])
    w.writerow(["Amina", "Yusuf", "staff", "Accounts", "Accountant", "amina@example.com", "08030000000"])
    w.writerow(["David", "Gyang", "student", "JSS 2", "JSS 2A", "", ""])
    return resp


@org_admin_required
@require_POST
def department_add(request):
    form = DepartmentForm(request.POST)
    if form.is_valid():
        Department.objects.get_or_create(organisation=request.user.organisation,
                                         name=form.cleaned_data["name"].strip())
        messages.success(request, "Department added.")
    return redirect(request.POST.get("next") or "members")


@org_admin_required
@require_POST
def department_delete(request, pk):
    get_object_or_404(Department, pk=pk, organisation=request.user.organisation).delete()
    messages.success(request, "Department removed.")
    return redirect("members")


# =========================================================================== #
# Admin: attendance records
# =========================================================================== #
@org_admin_required
def attendance(request):
    org = request.user.organisation
    today = timezone.localdate()
    d = _parse_date(request.GET.get("date"), today)
    dept = request.GET.get("dept", "")
    members_qs = org.members.filter(is_active=True).select_related("department")
    if dept:
        members_qs = members_qs.filter(department_id=dept)
    recs = {r.user_id: r for r in AttendanceRecord.objects.filter(organisation=org, date=d)}
    rows = []
    for m in members_qs:
        r = recs.get(m.id)
        if r:
            state = r.status
        elif d > today or not org.is_working_day(d):
            state = "none"
        else:
            state = "absent"
        rows.append({"m": m, "r": r, "state": state})
    order = {"late": 1, "present": 0, "leave": 2, "absent": 3, "none": 4}
    rows.sort(key=lambda x: (order[x["state"]], x["r"].check_in if x["r"] and x["r"].check_in else timezone.now()))
    counts = {k: sum(1 for x in rows if x["state"] == k) for k in order}
    return render(request, "manage/attendance.html", {
        "rows": rows, "d": d, "prev": d - timedelta(days=1), "next": d + timedelta(days=1),
        "is_today": d == today, "dept": dept, "departments": org.departments.all(), "counts": counts,
        "is_working_day": org.is_working_day(d)})


@org_admin_required
def record_add(request):
    org = request.user.organisation
    initial = {"date": request.GET.get("date") or timezone.localdate(), "status": "present"}
    if request.GET.get("user"):
        initial["user"] = request.GET["user"]
    form = RecordForm(org, request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        rec = form.save()
        messages.success(request, f"Attendance saved for {rec.user.display_name}.")
        return redirect(f"{reverse('attendance')}?date={rec.date}")
    return render(request, "manage/record_form.html", {"form": form, "title": "Add attendance entry"})


@org_admin_required
def record_edit(request, pk):
    org = request.user.organisation
    rec = get_object_or_404(AttendanceRecord, pk=pk, organisation=org)
    form = RecordForm(org, request.POST or None, instance=rec)
    if request.method == "POST":
        if "delete" in request.POST:
            d = rec.date
            rec.delete()
            messages.success(request, "Entry deleted.")
            return redirect(f"{reverse('attendance')}?date={d}")
        if form.is_valid():
            rec = form.save()
            messages.success(request, "Entry updated.")
            return redirect(f"{reverse('attendance')}?date={rec.date}")
    return render(request, "manage/record_form.html", {"form": form, "rec": rec, "title": "Edit attendance entry"})


@org_admin_required
@feature_required(catalog.AUDIT_TRAIL)
def scan_logs(request):
    logs = ScanLog.objects.filter(organisation=request.user.organisation).select_related("user")[:300]
    return render(request, "manage/logs.html", {"logs": logs})


# =========================================================================== #
# Admin: reports
# =========================================================================== #
@org_admin_required
@feature_required(catalog.ADVANCED_REPORTS)
def reports(request):
    org = request.user.organisation
    today = timezone.localdate()
    preset = request.GET.get("preset", "")
    if preset == "week":
        start, end = today - timedelta(days=today.weekday()), today
    elif preset == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    else:
        start = _parse_date(request.GET.get("start"), today.replace(day=1))
        end = _parse_date(request.GET.get("end"), today)
    if end < start:
        start, end = end, start
    if (end - start).days > 366:
        messages.warning(request, "Reports are limited to one year; the range was shortened.")
        start = end - timedelta(days=366)

    dept = request.GET.get("dept", "")
    members_qs = org.members.filter(is_active=True).select_related("department")
    if dept:
        members_qs = members_qs.filter(department_id=dept)
    report = services.build_report(org, start, end, members=members_qs)

    fmt = request.GET.get("export")
    if fmt in ("xlsx", "csv") and not org.has_feature(catalog.EXPORTS):
        messages.warning(request, upgrade_message(catalog.EXPORTS))
        return redirect("billing")
    if fmt in ("xlsx", "csv"):
        data = services.export_xlsx(org, report) if fmt == "xlsx" else services.export_csv(org, report)
        fname = f"{org.code}-attendance-{start}-to-{end}.{fmt}"
        if request.GET.get("save"):
            dept_name = org.departments.filter(pk=dept).first() if dept else None
            title = f"Attendance {start:%d %b} – {end:%d %b %Y}" + (f" · {dept_name}" if dept_name else "")
            rep = SavedReport(organisation=org, title=title, start_date=start, end_date=end,
                              file_format=fmt, created_by=request.user)
            rep.file.save(fname, ContentFile(data), save=True)
            messages.success(request, "Report saved to your report library.")
            return redirect("saved_reports")
        ctype = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx"
                 else "text/csv")
        resp = HttpResponse(data, content_type=ctype)
        resp["Content-Disposition"] = f'attachment; filename="{fname}"'
        return resp

    return render(request, "manage/reports.html", {
        "report": report, "start": start, "end": end, "dept": dept, "departments": org.departments.all(),
        "query": request.GET.urlencode()})


@org_admin_required
@feature_required(catalog.ADVANCED_REPORTS)
def saved_reports(request):
    reps = SavedReport.objects.filter(organisation=request.user.organisation).select_related("created_by")
    return render(request, "manage/saved_reports.html", {"reps": reps})


@org_admin_required
@feature_required(catalog.ADVANCED_REPORTS)
def saved_report_download(request, pk):
    rep = get_object_or_404(SavedReport, pk=pk, organisation=request.user.organisation)
    resp = HttpResponse(rep.file.read(), content_type="application/octet-stream")
    resp["Content-Disposition"] = f'attachment; filename="{rep.file.name.split("/")[-1]}"'
    return resp


@org_admin_required
@require_POST
def saved_report_delete(request, pk):
    rep = get_object_or_404(SavedReport, pk=pk, organisation=request.user.organisation)
    rep.file.delete(save=False)
    rep.delete()
    messages.success(request, "Report deleted.")
    return redirect("saved_reports")


# =========================================================================== #
# Admin: settings & QR
# =========================================================================== #
@org_admin_required
def org_settings(request):
    org = request.user.organisation
    form = OrgSettingsForm(request.POST or None, request.FILES or None, instance=org,
                           branding=org.has_feature(catalog.CUSTOM_BRANDING))
    if request.method == "POST":
        if "rotate_key" in request.POST:
            org.rotate_kiosk_key()
            messages.success(request, "Reception link changed. Open the new link on your reception screen.")
            return redirect("org_settings")
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("org_settings")
    kiosk_url = request.build_absolute_uri(reverse("kiosk", args=[org.kiosk_key]))
    return render(request, "manage/settings.html", {"form": form, "kiosk_url": kiosk_url})
