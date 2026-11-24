"""The Android / iPhone apps (mobile/) are native shells that open this website, so every change
deployed here reaches the apps on their next page load. These views are the few app-only extras."""
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

APP_UA = "AttendProApp/"


def is_app(request):
    return APP_UA in request.META.get("HTTP_USER_AGENT", "")


def app_platform(request):
    ua = request.META.get("HTTP_USER_AGENT", "")
    if APP_UA not in ua:
        return ""
    return "ios" if f"{APP_UA}ios" in ua else "android"


@never_cache
def start(request):
    """Where the app opens: the dashboard / portal if signed in, otherwise sign-in."""
    return redirect("home" if request.user.is_authenticated else "login")


@never_cache
def config(request):
    """Read by static/js/app-bridge.js when the app starts."""
    return JsonResponse({
        "min_version": settings.APP_MIN_VERSION,
        "android_url": settings.APP_ANDROID_URL,
        "ios_url": settings.APP_IOS_URL,
        "signed_in": request.user.is_authenticated,
    })


def in_app(request):
    """Template context: `in_app` and `app_platform` for pages that adapt inside the app."""
    platform = app_platform(request)
    return {"in_app": bool(platform), "app_platform": platform}
