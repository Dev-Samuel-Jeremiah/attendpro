"""Create the built-in features and the Basic / Professional / Enterprise plans.

Uses a frozen copy of the catalogue so later edits to billing/catalog.py don't change history.
Existing rows (matched by code / slug) are left alone, so the super admin's edits survive.
"""
from django.db import migrations

FEATURES = [
    ("manual_clock", "Clock-in button with location check",
     "Members clock in from their phone, only when they are at your premises", "live", "bpe"),
    ("clock_in_out", "Clock-in and clock-out", "Arrival, departure and hours worked", "live", "bpe"),
    ("daily_dashboard", "Daily attendance dashboard", "Who is in, late or absent today", "live", "bpe"),
    ("attendance_history", "Basic attendance history", "Each member sees their own record", "live", "bpe"),
    ("single_branch", "One branch", "", "live", "bp"),
    ("qr_attendance", "QR code attendance", "Rotating QR code on a reception screen", "live", "pe"),
    ("advanced_reports", "Advanced attendance reports",
     "Any date range, department filter, saved report library", "live", "pe"),
    ("leave_management", "Leave management", "Leave requests and approvals", "coming_soon", "pe"),
    ("self_service", "Staff self-service", "Members download their own attendance history", "live", "pe"),
    ("exports", "Excel and PDF export", "Excel and CSV downloads now; PDF coming soon", "live", "pe"),
    ("notifications", "Automated notifications", "Late and absence alerts", "coming_soon", "pe"),
    ("geofencing", "GPS and geofencing", "Location check on every scan, several sites", "coming_soon", "e"),
    ("face_verification", "Face verification", "Selfie check at clock-in", "coming_soon", "e"),
    ("payroll", "Payroll integration", "Hours and lateness feed into payroll", "coming_soon", "e"),
    ("multi_branch", "Multiple branches", "", "coming_soon", "e"),
    ("advanced_analytics", "Advanced analytics", "Trends and patterns across your organisation", "coming_soon", "e"),
    ("custom_branding", "Custom branding", "Your logo across the app and reception screen", "live", "e"),
    ("audit_trail", "Audit trail", "Every scan attempt with time, IP address and location", "live", "e"),
    ("priority_support", "Priority technical support", "", "live", "e"),
    ("advanced_backup", "Advanced backup and recovery", "", "coming_soon", "e"),
]

PLANS = [
    ("b", "Basic", "basic", "For small teams getting started. Free forever.", 0, 10, False, True),
    ("p", "Professional", "professional", "QR attendance, reports and exports for growing teams.", 10000, 25, True, False),
    ("e", "Enterprise", "enterprise", "Everything, for large and multi-site organisations.", 30000, None, False, False),
]


def seed(apps, schema_editor):
    Feature = apps.get_model("billing", "Feature")
    Plan = apps.get_model("billing", "Plan")
    plans = {}
    for i, (key, name, slug, tagline, price, limit, highlight, default) in enumerate(PLANS):
        plans[key], _ = Plan.objects.get_or_create(slug=slug, defaults=dict(
            name=name, tagline=tagline, price=price, period_days=30, staff_limit=limit,
            highlight=highlight, is_default=default, sort_order=(i + 1) * 10))
    for i, (code, name, desc, status, keys) in enumerate(FEATURES):
        feature, created = Feature.objects.get_or_create(code=code, defaults=dict(
            name=name, description=desc, status=status, is_builtin=True, sort_order=(i + 1) * 10))
        if created:
            for k in keys:
                plans[k].features.add(feature)


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
