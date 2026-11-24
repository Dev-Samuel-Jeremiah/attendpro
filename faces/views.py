from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from billing import catalog
from billing.services import feature_required
from core.decorators import org_admin_required
from core.models import User

from . import engine, services
from .models import FaceCheck, FaceProfile


@org_admin_required
@feature_required(catalog.FACE)
def faces(request):
    org = request.user.organisation
    tab = request.GET.get("tab", "review")
    to_review = FaceProfile.objects.filter(organisation=org, reviewed=False).select_related("user")
    checks = FaceCheck.objects.filter(organisation=org).select_related("user", "user__face")
    if tab == "refused":
        checks = checks.filter(result__in=[FaceCheck.MISMATCH, FaceCheck.NO_FACE])
    members = org.members.filter(is_active=True)
    return render(request, "faces/faces.html", {
        "tab": tab, "to_review": to_review, "checks": checks[:120],
        "enrolled": FaceProfile.objects.filter(organisation=org, user__is_active=True).count(),
        "total": members.count(), "engine_ready": engine.available(),
        "not_enrolled": members.filter(face__isnull=True).order_by("first_name")[:50]})


@org_admin_required
@feature_required(catalog.FACE)
@require_POST
def face_review(request, pk):
    profile = get_object_or_404(FaceProfile, pk=pk, organisation=request.user.organisation)
    if request.POST.get("action") == "reset":
        services.reset(profile.user)
        messages.success(request, f"{profile.user.display_name}'s face was removed. Their next selfie becomes the new reference.")
    else:
        profile.reviewed = True
        profile.save(update_fields=["reviewed"])
        messages.success(request, f"{profile.user.display_name}'s face confirmed.")
    return redirect(request.POST.get("next") or "faces")


@org_admin_required
@feature_required(catalog.FACE)
@require_POST
def face_enrol(request, user_pk):
    member = get_object_or_404(User, pk=user_pk, organisation=request.user.organisation)
    if request.POST.get("action") == "reset":
        services.reset(member)
        messages.success(request, f"{member.display_name}'s face was removed.")
    else:
        upload = request.FILES.get("photo")
        try:
            if not upload:
                raise services.SelfieError("Choose or take a photo first.")
            if upload.size > services.MAX_IMAGE_BYTES:
                raise services.SelfieError("That photo is too large (6 MB at most).")
            services.enrol(member, upload.read())
            messages.success(request, f"Face registered for {member.display_name}.")
        except services.SelfieError as e:
            messages.error(request, str(e))
    return redirect("member_edit", pk=member.pk)


@org_admin_required
@feature_required(catalog.FACE)
def face_photo(request, kind, pk):
    """Serve a private face photo, only to administrators of the same organisation."""
    org = request.user.organisation
    obj = get_object_or_404(FaceProfile if kind == "ref" else FaceCheck, pk=pk, organisation=org)
    if not obj.photo:
        raise Http404
    resp = FileResponse(obj.photo.open("rb"), content_type="image/jpeg")
    resp["Cache-Control"] = "private, max-age=600"
    return resp
