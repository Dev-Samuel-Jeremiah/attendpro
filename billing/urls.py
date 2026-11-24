from django.urls import path

from . import platform_views as pv
from . import site_views, views

urlpatterns = [
    path("pricing/", views.pricing, name="pricing"),
    path("contact/", site_views.contact, name="contact"),
    path("privacy/", site_views.privacy, name="privacy"),
    path("terms/", site_views.terms, name="terms"),
    path("account/delete/", site_views.delete_account, name="delete_account"),
    path("manage/billing/", views.billing, name="billing"),
    path("manage/billing/checkout/<slug:slug>/", views.checkout, name="checkout"),
    path("manage/billing/callback/", views.paystack_callback, name="paystack_callback"),
    path("billing/paystack/webhook/", views.paystack_webhook, name="paystack_webhook"),

    path("platform/", pv.overview, name="platform"),
    path("platform/organisations/<int:pk>/", pv.org_plan, name="platform_org"),
    path("platform/plans/", pv.plans, name="platform_plans"),
    path("platform/plans/add/", pv.plan_edit, name="platform_plan_add"),
    path("platform/plans/<int:pk>/", pv.plan_edit, name="platform_plan_edit"),
    path("platform/features/", pv.features, name="platform_features"),
    path("platform/features/add/", pv.feature_edit, name="platform_feature_add"),
    path("platform/features/<int:pk>/", pv.feature_edit, name="platform_feature_edit"),
    path("platform/features/<int:pk>/delete/", pv.feature_delete, name="platform_feature_delete"),
    path("platform/payments/", pv.payments, name="platform_payments"),
    path("platform/site/", pv.site_settings, name="platform_site"),
    path("platform/messages/", pv.contact_messages, name="platform_messages"),
    path("platform/testimonials/", pv.testimonials, name="platform_testimonials"),
    path("platform/testimonials/add/", pv.testimonial_edit, name="platform_testimonial_add"),
    path("platform/testimonials/<int:pk>/", pv.testimonial_edit, name="platform_testimonial_edit"),
]
