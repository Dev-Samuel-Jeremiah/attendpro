from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AttendanceRecord, Department, Organisation, SavedReport, ScanLog, User


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "org_type", "work_start", "created_at")
    search_fields = ("name", "code")


@admin.register(User)
class AttendUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "organisation", "role", "department", "is_active")
    list_filter = ("organisation", "role", "category", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Organisation", {"fields": ("organisation", "role", "category", "department", "designation",
                                     "phone", "photo")}),
    )


admin.site.register(Department)


@admin.register(AttendanceRecord)
class AttendanceAdmin(admin.ModelAdmin):
    """Read-only apart from the note: clock-in/out times come only from people's own scans."""
    list_display = ("user", "date", "check_in", "check_out", "status", "source")
    list_filter = ("organisation", "status", "source", "date")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    readonly_fields = ("organisation", "user", "date", "check_in", "check_out", "status", "source",
                       "check_in_ip", "check_out_ip", "branch", "leave_request", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return obj is not None and not obj.is_locked

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(ScanLog)
class ScanLogAdmin(admin.ModelAdmin):
    list_display = ("user", "timestamp", "action", "ip")
    list_filter = ("organisation", "action")


admin.site.register(SavedReport)
