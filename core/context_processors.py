def organisation(request):
    user = getattr(request, "user", None)
    authed = bool(user and user.is_authenticated)
    org = getattr(user, "organisation", None) if authed else None
    is_admin = authed and getattr(user, "is_org_admin", False)
    return {
        "org": org,
        # Pages shared by admins and members render inside the right shell.
        "layout": "manage/_shell.html" if is_admin else "staff/_shell.html",
    }
