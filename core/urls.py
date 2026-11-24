from django.urls import path

from . import analytics_views, app_views, branch_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_org, name="register"),
    path("app/", app_views.start, name="app_start"),
    path("app/config/", app_views.config, name="app_config"),
    path("app/welcome/", app_views.welcome, name="app_welcome"),
    path("app/welcome/done/", app_views.welcome_done, name="app_welcome_done"),
    path("app/get/", app_views.get_app, name="get_app"),
    path("register/check-code/", views.register_check_code, name="register_check_code"),

    # Scanning
    path("scan/", views.scan, name="scan"),
    path("scanner/", views.scanner, name="scanner"),
    path("api/scan/", views.api_scan, name="api_scan"),
    path("api/clock/", views.api_clock, name="api_clock"),

    # Reception display
    path("kiosk/<str:key>/", views.kiosk, name="kiosk"),
    path("kiosk/<str:key>/token/", views.kiosk_token, name="kiosk_token"),

    # Member portal
    path("me/", views.portal, name="portal"),
    path("me/history/", views.my_history, name="my_history"),
    path("me/password/", views.change_password, name="change_password"),

    # Organisation admin
    path("manage/", views.dashboard, name="dashboard"),
    path("manage/live/", views.live_feed, name="live_feed"),
    path("manage/members/", views.members, name="members"),
    path("manage/members/add/", views.member_add, name="member_add"),
    path("manage/members/import/", views.member_import, name="member_import"),
    path("manage/members/import/template.csv", views.import_template, name="import_template"),
    path("manage/members/credentials/", views.credentials, name="credentials"),
    path("manage/members/<int:pk>/", views.member_edit, name="member_edit"),
    path("manage/members/<int:pk>/reset-password/", views.member_reset_password, name="member_reset_password"),
    path("manage/departments/add/", views.department_add, name="department_add"),
    path("manage/departments/<int:pk>/delete/", views.department_delete, name="department_delete"),
    path("manage/attendance/", views.attendance, name="attendance"),
    path("manage/attendance/add/", views.record_add, name="record_add"),
    path("manage/attendance/<int:pk>/", views.record_edit, name="record_edit"),
    path("manage/logs/", views.scan_logs, name="scan_logs"),
    path("manage/reports/", views.reports, name="reports"),
    path("manage/reports/saved/", views.saved_reports, name="saved_reports"),
    path("manage/reports/saved/<int:pk>/download/", views.saved_report_download, name="saved_report_download"),
    path("manage/reports/saved/<int:pk>/delete/", views.saved_report_delete, name="saved_report_delete"),
    path("manage/settings/", views.org_settings, name="org_settings"),
    path("manage/settings/qr-print/", views.qr_print, name="qr_print"),
    path("manage/analytics/", analytics_views.analytics_page, name="analytics"),
    path("manage/branches/", branch_views.branches, name="branches"),
    path("manage/branches/add/", branch_views.branch_edit, name="branch_add"),
    path("manage/branches/<int:pk>/", branch_views.branch_edit, name="branch_edit"),
]
