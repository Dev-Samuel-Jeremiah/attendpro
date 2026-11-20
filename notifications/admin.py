from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "organisation", "kind", "created_at", "read_at")
    list_filter = ("kind",)
