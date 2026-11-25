"""Remember who uses the AttendPro app (see core.models.AppActivity)."""
from django.utils import timezone

APP_UA = "AttendProApp/"
TOUCH_EVERY_SECONDS = 600     # update "last opened" at most every 10 minutes per signed-in session


class AppActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._record(request)
        except Exception:   # never let tracking break a page
            pass
        return response

    @staticmethod
    def _record(request):
        ua = request.META.get("HTTP_USER_AGENT", "")
        user = getattr(request, "user", None)
        if APP_UA not in ua or user is None or not user.is_authenticated or not hasattr(request, "session"):
            return
        now = timezone.now()
        last = request.session.get("app_seen_at", 0)
        if now.timestamp() - last < TOUCH_EVERY_SECONDS:
            return
        from .models import AppActivity
        platform = "ios" if f"{APP_UA}ios" in ua else "android"
        row, created = AppActivity.objects.get_or_create(
            user=user, date=timezone.localdate(), defaults={"platform": platform, "first_at": now, "last_at": now})
        if not created:
            AppActivity.objects.filter(pk=row.pk).update(last_at=now, platform=platform)
        request.session["app_seen_at"] = now.timestamp()
