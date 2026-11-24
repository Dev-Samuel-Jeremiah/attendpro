from django.urls import path

from . import views

urlpatterns = [
    path("manage/payroll/", views.payroll, name="payroll"),
    path("manage/payroll/rates/", views.pay_rates, name="pay_rates"),
    path("manage/payroll/rules/", views.pay_rules, name="pay_rules"),
    path("manage/payroll/<int:pk>/", views.payroll_run, name="payroll_run"),
    path("manage/payroll/payslip/<int:pk>/", views.payslip_admin, name="payslip_admin"),
    path("me/payslips/", views.my_payslips, name="my_payslips"),
    path("me/payslips/<int:pk>/", views.my_payslip, name="my_payslip"),
]
