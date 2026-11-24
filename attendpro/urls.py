from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "AttendPro Super Admin"
admin.site.site_title = "AttendPro"

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("", include("core.urls")),
    path("", include("billing.urls")),
    path("", include("leave.urls")),
    path("", include("notifications.urls")),
    path("", include("faces.urls")),
    path("", include("payroll.urls")),
    path("", include("recovery.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
