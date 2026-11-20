from django.contrib import admin

from .models import Feature, Payment, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "period_days", "staff_limit", "is_default", "is_public", "sort_order")
    filter_horizontal = ("features",)


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "status", "is_builtin", "sort_order")
    list_filter = ("status", "is_builtin")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "organisation", "plan", "amount_kobo", "status", "paid_at")
    list_filter = ("status", "plan")
    search_fields = ("reference", "organisation__name")
    readonly_fields = [f.name for f in Payment._meta.fields]
