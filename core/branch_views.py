"""Branches (Enterprise: multiple branches)."""
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from billing import catalog
from billing.services import feature_required

from .decorators import org_admin_required
from .forms import BranchForm
from .models import AttendanceRecord, Branch


@org_admin_required
@feature_required(catalog.MULTI_BRANCH)
def branches(request):
    org = request.user.organisation
    today = timezone.localdate()
    present = dict(AttendanceRecord.objects.filter(organisation=org, date=today, check_in__isnull=False)
                   .values_list("branch").annotate(n=Count("id")).values_list("branch", "n"))
    rows = []
    for b in org.branches.annotate(staff=Count("members", filter=Q(members__is_active=True))):
        rows.append({"b": b, "present": present.get(b.id, 0),
                     "kiosk_url": request.build_absolute_uri(reverse("kiosk", args=[b.kiosk_key]))})
    main_staff = org.members.filter(is_active=True, branch__isnull=True).count()
    return render(request, "manage/branches.html", {
        "rows": rows, "main_staff": main_staff, "main_present": present.get(None, 0),
        "main_kiosk_url": request.build_absolute_uri(reverse("kiosk", args=[org.kiosk_key])),
        "geofencing": org.has_feature(catalog.GEOFENCING)})


@org_admin_required
@feature_required(catalog.MULTI_BRANCH)
def branch_edit(request, pk=None):
    org = request.user.organisation
    obj = get_object_or_404(Branch, pk=pk, organisation=org) if pk else None
    form = BranchForm(org, request.POST or None, instance=obj)
    if request.method == "POST":
        if obj and "rotate_key" in request.POST:
            obj.rotate_kiosk_key()
            messages.success(request, f"{obj.name} has a new reception link. Open it on that branch's screen.")
            return redirect("branch_edit", pk=obj.pk)
        if form.is_valid():
            b = form.save()
            messages.success(request, f"{b.name} saved.")
            return redirect("branches")
    kiosk_url = request.build_absolute_uri(reverse("kiosk", args=[obj.kiosk_key])) if obj else ""
    return render(request, "manage/branch_form.html", {"form": form, "obj": obj, "kiosk_url": kiosk_url})
