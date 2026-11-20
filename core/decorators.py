from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def org_admin_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *a, **kw):
        if not request.user.organisation_id or not request.user.is_org_admin:
            messages.error(request, "That page is for administrators only.")
            return redirect("home")
        return view(request, *a, **kw)
    return wrapper


def member_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *a, **kw):
        if not request.user.organisation_id:
            messages.error(request, "Your account is not linked to an organisation.")
            return redirect("login")
        return view(request, *a, **kw)
    return wrapper
