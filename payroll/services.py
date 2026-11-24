"""Turn a month of attendance into pay. Figures come from build_report, so they match the Reports page."""
import calendar
import csv
import io
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from core.services import build_report

from .models import PayProfile, PayrollLine, PayrollRun, PaySettings

CENT = Decimal("0.01")


def money(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def settings_for(org):
    return PaySettings.objects.get_or_create(organisation=org)[0]


def profile_for(user):
    return PayProfile.objects.get_or_create(user=user)[0]


def month_bounds(month: date):
    first = month.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return first, last


def day_hours(org):
    start = datetime.combine(date.today(), org.work_start)
    end = datetime.combine(date.today(), org.work_end)
    hours = (end - start).total_seconds() / 3600
    return Decimal(str(round(hours, 2))) if hours > 0 else Decimal("8")


def calculate(org, rules, profile, row, working_days, first):
    """Figures for one person. `row` is that person's build_report row for the month."""
    recs = row["records"].values()
    unpaid = sum(1 for r in recs if r.status == "leave" and r.leave_request_id and not r.leave_request.leave_type.is_paid)
    paid_leave = row["leave"] - unpaid
    rate = money(profile.rate)
    hours = money(row["hours"])
    absent_days = row["absent"] + (unpaid if rules.deduct_unpaid_leave else 0)

    if profile.pay_type == PayProfile.MONTHLY:
        joined = timezone.localdate(row["user"].date_joined)
        gross = rate
        if joined > first and working_days:  # joined during the month: pay only the days since
            since = sum(1 for d in row["days_all"] if d >= joined)
            gross = money(rate * since / working_days)
        daily = rate / working_days if working_days else Decimal("0")
        if rules.absence_mode == PaySettings.ABSENCE_DAILY:
            absence = money(daily * absent_days)
        elif rules.absence_mode == PaySettings.ABSENCE_FIXED:
            absence = money(rules.absence_fee * absent_days)
        else:
            absence = Decimal("0")
    elif profile.pay_type == PayProfile.DAILY:
        gross = money(rate * (row["attended"] + paid_leave))
        absence = Decimal("0")          # absent days are simply not paid
    else:
        gross = money(rate * hours + rate * day_hours(org) * paid_leave)
        absence = Decimal("0")

    late = money(max(0, row["late"] - rules.free_lates) * rules.late_fee)
    return {"pay_type": profile.pay_type, "rate": rate, "working_days": working_days, "expected": row["expected"],
            "attended": row["attended"], "late": row["late"], "absent": row["absent"], "paid_leave": paid_leave,
            "unpaid_leave": unpaid, "hours": hours, "gross": gross, "late_deduction": late,
            "absence_deduction": min(absence, gross)}


def finish(line):
    line.net = max(Decimal("0"), money(line.gross - line.late_deduction - line.absence_deduction + line.adjustment))
    return line


@transaction.atomic
def prepare(org, month: date, by):
    """Create or recalculate the draft run for `month`, keeping any adjustments already typed in."""
    first, last = month_bounds(month)
    run, _ = PayrollRun.objects.get_or_create(organisation=org, month=first, defaults={"created_by": by})
    if run.is_final:
        raise ValueError("This month's payroll is finalised and can't be recalculated.")
    rules = settings_for(org)
    members = list(org.members.filter(is_active=True, date_joined__date__lte=last).select_related("department"))
    report = build_report(org, first, last, members=members)
    working = [d for d in report["days"] if org.is_working_day(d)]
    kept = {l.user_id: l for l in run.lines.all()}
    seen = set()
    for row in report["rows"]:
        row["days_all"] = working
        u = row["user"]
        values = calculate(org, rules, profile_for(u), row, len(working), first)
        line = kept.get(u.id) or PayrollLine(run=run, user=u)
        for k, v in values.items():
            setattr(line, k, v)
        finish(line).save()
        seen.add(u.id)
    run.lines.exclude(user_id__in=seen).delete()
    return run


@transaction.atomic
def finalise(run, by):
    from notifications.services import notify
    run.status, run.finalised_at = PayrollRun.FINAL, timezone.now()
    run.save(update_fields=["status", "finalised_at"])
    notify(run.organisation, [l.user for l in run.lines.select_related("user")], f"Your payslip for {run} is ready",
           "Open AttendPro to see it.", url="/me/payslips/", kind="pay")
    return run


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #
HEADERS = ["ID", "Name", "Pay type", "Rate", "Working days", "Expected", "Attended", "Late", "Absent",
           "Paid leave", "Unpaid leave", "Hours", "Gross", "Late deduction", "Absence deduction",
           "Adjustment", "Adjustment note", "Net pay"]


def line_values(l):
    return [l.user.username, l.user.display_name, l.get_pay_type_display(), l.rate, l.working_days, l.expected,
            l.attended, l.late, l.absent, l.paid_leave, l.unpaid_leave, l.hours, l.gross, l.late_deduction,
            l.absence_deduction, l.adjustment, l.adjustment_note, l.net]


def export_csv(run) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"{run.organisation.name} payroll", f"{run}", run.get_status_display()])
    w.writerow(HEADERS)
    for l in run.lines.select_related("user"):
        w.writerow(line_values(l))
    return buf.getvalue().encode("utf-8-sig")


def export_bank_csv(run) -> bytes:
    """One row per person paid: what a bank's bulk-transfer upload usually asks for."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Account name", "Account number", "Bank", "Amount", "Narration"])
    for l in run.lines.select_related("user", "user__pay"):
        if l.net <= 0:
            continue
        p = getattr(l.user, "pay", None)
        w.writerow([(p.account_name if p else "") or l.user.display_name, p.account_number if p else "",
                    p.bank_name if p else "", l.net, f"Salary {run.month:%b %Y}"])
    return buf.getvalue().encode("utf-8-sig")


def export_xlsx(run) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = f"{run.month:%b %Y}"
    ws["A1"] = f"{run.organisation.name} · Payroll {run}"
    ws["A1"].font = Font(bold=True, size=14, color="1E2A4A")
    ws["A2"] = f"{run.get_status_display()} · generated {timezone.localtime():%d %b %Y, %I:%M %p}"
    ws.append([])
    ws.append(HEADERS)
    for c in ws[4]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1E2A4A")
    total = Decimal("0")
    for l in run.lines.select_related("user"):
        ws.append([float(v) if isinstance(v, Decimal) else v for v in line_values(l)])
        total += l.net
    ws.append([])
    ws.append(["", "Total net pay"] + [""] * 15 + [float(total)])
    ws.cell(row=ws.max_row, column=2).font = Font(bold=True)
    for i, wdt in enumerate([12, 26, 14, 12] + [10] * 8 + [13, 13, 13, 12, 22, 13], 1):
        ws.column_dimensions[ws.cell(row=4, column=i).column_letter].width = wdt
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def payslip_pdf(line) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    run, user, org = line.run, line.user, line.run.organisation
    navy, muted, line_c = colors.HexColor("#1E2A4A"), colors.HexColor("#6B7280"), colors.HexColor("#D9DEE8")
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=navy)
    s = ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=muted)

    def naira(x):
        return f"N{x:,.2f}"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A5, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"Payslip {run} {user.username}")
    who = [["Name", user.display_name], ["ID", user.username], ["Department", str(user.department or "—")],
           ["Pay", f"{line.get_pay_type_display()} · {naira(line.rate)}"]]
    att = [["Working days", line.working_days, "Attended", line.attended], ["Late", line.late, "Absent", line.absent],
           ["Paid leave", line.paid_leave, "Unpaid leave", line.unpaid_leave], ["Hours", line.hours, "", ""]]
    pay = [["Gross pay", naira(line.gross)], ["Late arrivals", f"-{naira(line.late_deduction)}"],
           ["Absences / unpaid leave", f"-{naira(line.absence_deduction)}"]]
    if line.adjustment:
        pay.append([line.adjustment_note or "Adjustment",
                    f"{'+' if line.adjustment > 0 else '-'}{naira(abs(line.adjustment))}"])
    pay.append(["Net pay", naira(line.net)])
    grid = TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (0, -1), muted),
                       ("LINEBELOW", (0, 0), (-1, -1), 0.4, line_c), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)])
    pay_style = TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9.5), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("LINEBELOW", (0, 0), (-1, -2), 0.4, line_c), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, -1), (-1, -1), 11.5),
                            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E3F8F0")),
                            ("TOPPADDING", (0, -1), (-1, -1), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 7)])
    story = [Paragraph(org.name, h), Paragraph(f"Payslip · {run} · {run.get_status_display()}", s), Spacer(0, 8),
             Table(who, colWidths=[30 * mm, 94 * mm], style=grid), Spacer(0, 10),
             Paragraph("Attendance", ParagraphStyle("t", parent=h, fontSize=10.5, leading=14)),
             Table(att, colWidths=[31 * mm] * 4, style=grid), Spacer(0, 10),
             Paragraph("Pay", ParagraphStyle("t2", parent=h, fontSize=10.5, leading=14)),
             Table(pay, colWidths=[84 * mm, 40 * mm], style=pay_style), Spacer(0, 12),
             Paragraph(f"Generated {timezone.localtime():%d %b %Y} by AttendPro from recorded attendance.", s)]
    doc.build(story)
    return buf.getvalue()
