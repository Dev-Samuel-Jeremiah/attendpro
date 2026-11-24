"""Feature codes the app checks before unlocking a page or button: `org.has_feature(QR_ATTENDANCE)`.

The features and plans themselves live in the database (seeded by
billing/migrations/0002_seed_plans.py) and are edited by the super admin on the Platform pages:
names, descriptions, prices, staff limits and which plan includes what. Removing one of these
features from a plan locks the matching part of the app for organisations on that plan.
"""
MANUAL_CLOCK = "manual_clock"         # clock-in button with location check
QR_ATTENDANCE = "qr_attendance"       # reception QR screen and scanning
ADVANCED_REPORTS = "advanced_reports"  # reports page and saved report library
EXPORTS = "exports"                   # Excel / CSV downloads of reports
SELF_SERVICE = "self_service"         # members download their own history
CUSTOM_BRANDING = "custom_branding"   # organisation logo
AUDIT_TRAIL = "audit_trail"           # scan log page
LEAVE = "leave_management"            # leave requests, approvals and balances
NOTIFICATIONS = "notifications"       # in-app + email alerts
MULTI_BRANCH = "multi_branch"         # several sites, each with its own location and reception QR
GEOFENCING = "geofencing"             # GPS check on QR scans too; clock in at any branch
ANALYTICS = "advanced_analytics"      # analytics page
FACE = "face_verification"            # selfie matched to a reference face at check-in
PAYROLL = "payroll"                   # pay rates, monthly payroll runs, payslips
BACKUP = "advanced_backup"            # weekly organisation backups, full export, recently deleted
