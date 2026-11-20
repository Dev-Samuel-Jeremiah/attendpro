from billing import catalog


def unread(request):
    """Badge counts for the sidebar: unread notifications and (for admins) leave awaiting a decision."""
    user = getattr(request, "user", None)
    org = getattr(user, "organisation", None) if user and user.is_authenticated else None
    if org is None:
        return {}
    out = {}
    if org.has_feature(catalog.NOTIFICATIONS):
        out["unread_count"] = user.notifications.filter(read_at__isnull=True).count()
    if user.is_org_admin and org.has_feature(catalog.LEAVE):
        out["leave_pending"] = org.leave_requests.filter(status="pending").count()
    return out
