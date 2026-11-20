from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from billing import catalog
from billing.services import feature_required
from core.decorators import member_required, org_admin_required

from . import services
from .forms import LeaveRequestForm, LeaveTypeForm
from .models import LeaveRequest, LeaveType


@member_required
@feature_required(catalog.LEAVE)
def my_leave(request):
    org = request.user.organisation
    services.ensure_types(org)
    form = LeaveRequestForm(org, request.POST or None)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        try:
            services.submit(request.user, cd["leave_type"], cd["start_date"], cd["end_date"], cd["reason"])
        except services.LeaveError as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, "Leave request sent. You'll be notified when it's decided.")
            return redirect("my_leave")
    return render(request, "leave/my_leave.html", {
        "form": form, "balances": services.balances(request.user), "year": timezone.localdate().year,
        "requests": request.user.leave_requests.select_related("leave_type", "reviewed_by")[:50]})


@member_required
@feature_required(catalog.LEAVE)
@require_POST
def my_leave_cancel(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk, user=request.user, status=LeaveRequest.PENDING)
    services.cancel(req, request.user)
    messages.success(request, "Leave request cancelled.")
    return redirect("my_leave")


@org_admin_required
@feature_required(catalog.LEAVE)
def leave_admin(request):
    org = request.user.organisation
    services.ensure_types(org)
    status = request.GET.get("status", "pending")
    qs = org.leave_requests.select_related("user", "user__department", "leave_type", "reviewed_by")
    if status in dict(LeaveRequest.STATUS_CHOICES):
        qs = qs.filter(status=status)
    today = timezone.localdate()
    return render(request, "leave/admin.html", {
        "requests": qs[:200], "status": status, "statuses": LeaveRequest.STATUS_CHOICES,
        "pending_count": org.leave_requests.filter(status=LeaveRequest.PENDING).count(),
        "on_leave": services.on_leave_today(org, today), "today": today,
        "types": org.leave_types.all(), "type_form": LeaveTypeForm(org)})


@org_admin_required
@feature_required(catalog.LEAVE)
@require_POST
def leave_decide(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk, organisation=request.user.organisation)
    note = request.POST.get("note", "").strip()
    action = request.POST.get("action")
    try:
        if action == "approve":
            services.approve(req, request.user, note)
            messages.success(request, f"Approved {req.user.display_name}'s leave. Those days now show as on leave.")
        elif action == "reject":
            services.reject(req, request.user, note)
            messages.success(request, f"Declined {req.user.display_name}'s request.")
        elif action == "cancel":
            services.cancel(req, request.user, note)
            messages.success(request, f"Cancelled {req.user.display_name}'s leave.")
    except services.LeaveError as e:
        messages.error(request, str(e))
    return redirect(request.POST.get("next") or "leave_admin")


@org_admin_required
@feature_required(catalog.LEAVE)
def leave_type_edit(request, pk=None):
    org = request.user.organisation
    obj = get_object_or_404(LeaveType, pk=pk, organisation=org) if pk else None
    form = LeaveTypeForm(org, request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Leave type saved.")
        return redirect("leave_admin")
    return render(request, "leave/type_form.html", {"form": form, "obj": obj})
