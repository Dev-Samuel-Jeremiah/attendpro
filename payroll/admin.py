from django.contrib import admin

from .models import PayrollLine, PayrollRun


class LineInline(admin.TabularInline):
    model = PayrollLine
    extra = 0
    fields = ("user", "gross", "late_deduction", "absence_deduction", "adjustment", "net")
    readonly_fields = fields


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ("organisation", "month", "status", "created_at")
    inlines = [LineInline]
