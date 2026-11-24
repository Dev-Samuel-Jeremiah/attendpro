from django.contrib import messages
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from billing import catalog
from billing.services import feature_required
from core.decorators import org_admin_required

from . import services
from .models import DeletedItem, OrgBackup


@org_admin_required
@feature_required(catalog.BACKUP)
def backups(request):
    org = request.user.organisation
    return render(request, "recovery/backups.html", {
        "backups": org.backups.all(), "keep": services.KEEP_AUTOMATIC, "days": services.KEEP_DELETED_DAYS,
        "deleted": org.deleted_items.filter(restored_at__isnull=True)[:200]})


@org_admin_required
@feature_required(catalog.BACKUP)
@require_POST
def backup_now(request):
    services.make_backup(request.user.organisation, OrgBackup.MANUAL, request.user)
    messages.success(request, "Backup made. You can download it below.")
    return redirect("backups")


@org_admin_required
@feature_required(catalog.BACKUP)
def backup_download(request, pk):
    b = get_object_or_404(OrgBackup, pk=pk, organisation=request.user.organisation)
    return FileResponse(b.file.open("rb"), as_attachment=True, filename=b.file.name.rsplit("/", 1)[-1],
                        content_type="application/zip")


@org_admin_required
@feature_required(catalog.BACKUP)
def export_now(request):
    org = request.user.organisation
    resp = HttpResponse(services.export_zip(org), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="{org.code}-attendpro-{timezone.localdate():%Y%m%d}.zip"'
    return resp


@org_admin_required
@feature_required(catalog.BACKUP)
@require_POST
def restore_item(request, pk):
    item = get_object_or_404(DeletedItem, pk=pk, organisation=request.user.organisation)
    try:
        services.restore(item, request.user)
        messages.success(request, f"Restored: {item.label}.")
    except services.RestoreError as e:
        messages.error(request, str(e))
    return redirect("backups")
