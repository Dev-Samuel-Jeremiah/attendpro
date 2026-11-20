from django.shortcuts import render
from django.utils import timezone

from billing import catalog
from billing.services import feature_required
from core.decorators import member_required


@member_required
@feature_required(catalog.NOTIFICATIONS)
def inbox(request):
    items = list(request.user.notifications.all()[:60])
    request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return render(request, "notifications/inbox.html", {"items": items, "unread_count": 0})
