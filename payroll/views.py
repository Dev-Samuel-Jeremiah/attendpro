from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from billing import catalog
from billing.services import feature_required
from core.decorators import member_required, org_admin_required
from core.forms import StyledMixin

from . import services
from .models import PayProfile, PayrollLine, PayrollRun, PaySettings


class RulesForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = PaySettings
        fields = ["late_fee", "free_lates", "absence_mode", "absence_fee", "deduct_unpaid_leave"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._style()


def _month(value, default):
    try:
        y, m = (int(x) for x in (value or "").split("-")[:2])
        return date(y, m, 1)
    except (TypeError, ValueError):
        return default


@org_admin_required
@feature_required(catalog.PAYROLL)
def payroll(request):
    org = request.user.organisation
    today = timezone.localdate()
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    if request.method == "POST":
        month = _month(request.POST.get("month"), last_month)
        try:
            run = services.prepare(org, month, request.user)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("payroll")
        messages.success(request, f"Payroll for {run} is ready to check.")
        return redirect("payroll_run", pk=run.pk)
    no_rate = org.members.filter(is_active=True).exclude(pay__rate__gt=0).count()
    return render(request, "payroll/index.html", {
        "runs": org.payroll_runs.all(), "default_month": last_month, "no_rate": no_rate,
        "rules": services.settings_for(org)})


@org_admin_required
@feature_required(catalog.PAYROLL)
def pay_rates(request):
    org = request.user.organisation
    members = list(org.members.filter(is_active=True).select_related("department"))
    profiles = {m.id: services.profile_for(m) for m in members}
    if request.method == "POST":
        errors = 0
        for m in members:
            p = profiles[m.id]
            p.pay_type = request.POST.get(f"t{m.id}", p.pay_type)
            if p.pay_type not in dict(PayProfile.TYPE_CHOICES):
                p.pay_type = PayProfile.MONTHLY
            try:
                rate = Decimal((request.POST.get(f"r{m.id}") or "0").replace(",", ""))
                if rate < 0:
                    raise InvalidOperation
                p.rate = rate
            except InvalidOperation:
                errors += 1
                continue
            p.bank_name = request.POST.get(f"b{m.id}", "")[:80].strip()
            p.account_number = "".join(ch for ch in request.POST.get(f"a{m.id}", "") if ch.isdigit())[:20]
            p.account_name = request.POST.get(f"n{m.id}", "")[:120].strip()
            p.save()
        if errors:
            messages.warning(request, f"{errors} rate(s) weren't numbers and were left unchanged.")
        else:
            messages.success(request, "Pay rates saved.")
        return redirect("pay_rates")
    return render(request, "payroll/rates.html", {"rows": [(m, profiles[m.id]) for m in members],
                                                  "types": PayProfile.TYPE_CHOICES})


@org_admin_required
@feature_required(catalog.PAYROLL)
def pay_rules(request):
    rules = services.settings_for(request.user.organisation)
    form = RulesForm(request.POST or None, instance=rules)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Payroll rules saved. Recalculate any draft payroll to apply them.")
        return redirect("payroll")
    return render(request, "payroll/rules.html", {"form": form})


@org_admin_required
@feature_required(catalog.PAYROLL)
def payroll_run(request, pk):
    run = get_object_or_404(PayrollRun, pk=pk, organisation=request.user.organisation)
    lines = list(run.lines.select_related("user", "user__department"))
    if request.method == "POST" and not run.is_final:
        action = request.POST.get("action")
        if action == "delete":
            run.delete()
            messages.success(request, "Draft payroll deleted.")
            return redirect("payroll")
        for l in lines:
            try:
                l.adjustment = Decimal((request.POST.get(f"adj{l.id}") or "0").replace(",", ""))
            except InvalidOperation:
                messages.error(request, f"The adjustment for {l.user.display_name} isn't a number.")
                return redirect("payroll_run", pk=run.pk)
            l.adjustment_note = request.POST.get(f"note{l.id}", "")[:120].strip()
            services.finish(l).save()
        if action == "recalculate":
            services.prepare(run.organisation, run.month, request.user)
            messages.success(request, "Recalculated from the latest attendance and rates.")
        elif action == "finalise":
            services.finalise(run, request.user)
            messages.success(request, f"Payroll for {run} finalised. Everyone can now see their payslip.")
        else:
            messages.success(request, "Adjustments saved.")
        return redirect("payroll_run", pk=run.pk)
    fmt = request.GET.get("export")
    if fmt:
        name = f"{run.organisation.code}-payroll-{run.month:%Y-%m}"
        if fmt == "xlsx":
            resp = HttpResponse(services.export_xlsx(run),
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            resp["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
        elif fmt == "bank":
            resp = HttpResponse(services.export_bank_csv(run), content_type="text/csv")
            resp["Content-Disposition"] = f'attachment; filename="{name}-bank-transfers.csv"'
        else:
            resp = HttpResponse(services.export_csv(run), content_type="text/csv")
            resp["Content-Disposition"] = f'attachment; filename="{name}.csv"'
        return resp
    totals = {k: sum((getattr(l, k) for l in lines), Decimal("0"))
              for k in ("gross", "late_deduction", "absence_deduction", "adjustment", "net")}
    return render(request, "payroll/run.html", {"run": run, "lines": lines, "totals": totals,
                                                "missing_bank": sum(1 for l in lines if l.net > 0 and not
                                                                    getattr(getattr(l.user, "pay", None), "account_number", ""))})


def _payslip_response(line):
    resp = HttpResponse(services.payslip_pdf(line), content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="payslip-{line.run.month:%Y-%m}-{line.user.username}.pdf"'
    return resp


@org_admin_required
@feature_required(catalog.PAYROLL)
def payslip_admin(request, pk):
    line = get_object_or_404(PayrollLine.objects.select_related("run", "user"), pk=pk,
                             run__organisation=request.user.organisation)
    return _payslip_response(line)


@member_required
@feature_required(catalog.PAYROLL)
def my_payslips(request):
    lines = (PayrollLine.objects.filter(user=request.user, run__status=PayrollRun.FINAL)
             .select_related("run").order_by("-run__month"))
    return render(request, "payroll/my_payslips.html", {"lines": lines})


@member_required
@feature_required(catalog.PAYROLL)
def my_payslip(request, pk):
    line = get_object_or_404(PayrollLine.objects.select_related("run", "user"), pk=pk, user=request.user,
                             run__status=PayrollRun.FINAL)
    return _payslip_response(line)

