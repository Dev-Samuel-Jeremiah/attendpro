import hashlib
import hmac
import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing import services
from billing.models import Feature, Payment, Plan
from core.models import Organisation, User

SECRET = "sk_test_dummy"


class PlanSetupMixin:
    def setUp(self):
        self.basic = Plan.objects.get(slug="basic")
        self.pro = Plan.objects.get(slug="professional")
        self.ent = Plan.objects.get(slug="enterprise")
        self.org = Organisation.objects.create(code="ACME", name="Acme", email="ops@acme.test")
        self.admin = User.objects.create_user(username="ACME-0001", password="pw-123456", organisation=self.org,
                                              role=User.ROLE_ADMIN, email="boss@acme.test")
        self.client.force_login(self.admin)

    def set_plan(self, plan, expires=None):
        self.org.plan, self.org.plan_expires_at = plan, expires
        self.org.save()


class SeedTests(TestCase):
    def test_three_plans_with_prices_and_limits(self):
        plans = {p.slug: p for p in Plan.objects.all()}
        self.assertEqual((plans["basic"].price, plans["basic"].staff_limit, plans["basic"].is_default), (0, 10, True))
        self.assertEqual((plans["professional"].price, plans["professional"].staff_limit), (10000, 25))
        self.assertEqual((plans["enterprise"].price, plans["enterprise"].staff_limit), (30000, None))

    def test_each_plan_includes_the_one_below(self):
        b, p, e = (set(Plan.objects.get(slug=s).feature_codes()) for s in ("basic", "professional", "enterprise"))
        self.assertTrue(b - {"single_branch"} <= p <= e | {"single_branch"})
        self.assertIn("qr_attendance", p)
        self.assertNotIn("qr_attendance", b)
        self.assertIn("manual_clock", b)


class GatingTests(PlanSetupMixin, TestCase):
    def test_no_plan_means_basic(self):
        self.assertEqual(self.org.current_plan, self.basic)

    def test_expired_paid_plan_falls_back_to_basic(self):
        self.set_plan(self.pro, timezone.now() - timedelta(minutes=1))
        org = Organisation.objects.get(pk=self.org.pk)
        self.assertEqual(org.current_plan, self.basic)
        self.assertFalse(org.has_feature("qr_attendance"))

    def test_basic_redirects_locked_pages_to_billing(self):
        for name in ("reports", "saved_reports", "scan_logs"):
            resp = self.client.get(reverse(name))
            self.assertRedirects(resp, reverse("billing"), msg_prefix=name)

    def test_professional_unlocks_reports_but_not_audit_trail(self):
        self.set_plan(self.pro, timezone.now() + timedelta(days=5))
        self.assertEqual(self.client.get(reverse("reports")).status_code, 200)
        self.assertRedirects(self.client.get(reverse("scan_logs")), reverse("billing"))

    def test_kiosk_token_blocked_on_basic(self):
        self.assertEqual(self.client.get(reverse("kiosk_token", args=[self.org.kiosk_key])).status_code, 403)
        self.set_plan(self.pro)
        self.assertEqual(self.client.get(reverse("kiosk_token", args=[self.org.kiosk_key])).status_code, 200)

    def test_removing_feature_from_plan_locks_it(self):
        self.set_plan(self.pro)
        self.pro.features.remove(Feature.objects.get(code="advanced_reports"))
        self.assertRedirects(self.client.get(reverse("reports")), reverse("billing"))

    def test_all_admin_pages_render_on_every_plan(self):
        names = ["dashboard", "attendance", "members", "org_settings", "billing", "portal", "my_history"]
        for plan in (self.basic, self.pro, self.ent):
            self.set_plan(plan)
            for name in names:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, f"{name} on {plan}")
            self.assertEqual(self.client.get(reverse("kiosk", args=[self.org.kiosk_key])).status_code, 200)

    def test_logo_field_only_with_custom_branding(self):
        self.assertNotIn('name="logo"', self.client.get(reverse("org_settings")).content.decode())
        self.set_plan(self.ent)
        self.assertIn('name="logo"', self.client.get(reverse("org_settings")).content.decode())


class StaffLimitTests(PlanSetupMixin, TestCase):
    def fill(self, n):
        for i in range(n):
            User.objects.create_user(username=f"ACME-{i + 2:04d}", password="x", organisation=self.org)

    def test_basic_blocks_the_eleventh_account(self):
        self.fill(9)  # 10 with the admin
        self.assertEqual(self.org.seats_left(), 0)
        self.assertRedirects(self.client.get(reverse("member_add")), reverse("billing"))

    def test_import_rejected_when_too_many(self):
        self.fill(7)  # 8 used, 2 left
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = b"first_name,last_name\nA,B\nC,D\nE,F\n"
        resp = self.client.post(reverse("member_import"), {"file": SimpleUploadedFile("m.csv", csv)})
        self.assertContains(resp, "room for 2 more")
        self.assertEqual(self.org.members.count(), 8)

    def test_reactivating_over_limit_refused(self):
        self.fill(9)
        m = User.objects.get(username="ACME-0002")
        m.is_active = False
        m.save()
        self.fill_one = User.objects.create_user(username="ACME-0099", password="x", organisation=self.org)
        resp = self.client.post(reverse("member_edit", args=[m.pk]), {
            "first_name": "A", "last_name": "B", "category": "staff", "role": "member", "is_active": "on"})
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertFalse(m.is_active)

    def test_enterprise_unlimited(self):
        self.set_plan(self.ent)
        self.fill(30)
        self.assertIsNone(self.org.seats_left())
        self.assertEqual(self.client.get(reverse("member_add")).status_code, 200)


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
class PaystackTests(PlanSetupMixin, TestCase):
    def pending(self, plan):
        return Payment.objects.create(organisation=self.org, plan=plan, amount_kobo=plan.price * 100,
                                      reference=f"REF-{plan.slug}-{Payment.objects.count()}")

    def test_successful_payment_activates_plan_once(self):
        p = self.pending(self.pro)
        data = {"status": "success", "amount": 1_000_000, "currency": "NGN", "channel": "card"}
        services.apply_paystack_result(p, data)
        services.apply_paystack_result(p, data)  # webhook + callback both arrive
        self.org.refresh_from_db()
        self.assertEqual(self.org.plan, self.pro)
        self.assertAlmostEqual((self.org.plan_expires_at - timezone.now()).days, 29, delta=1)
        p.refresh_from_db()
        self.assertEqual(p.status, "success")

    def test_wrong_amount_does_not_activate(self):
        p = self.pending(self.ent)
        services.apply_paystack_result(p, {"status": "success", "amount": 100, "currency": "NGN"})
        self.org.refresh_from_db()
        self.assertIsNone(self.org.plan)

    def test_early_renewal_extends_from_expiry(self):
        end = timezone.now() + timedelta(days=10)
        self.set_plan(self.pro, end)
        services.apply_paystack_result(self.pending(self.pro), {"status": "success", "amount": 1_000_000})
        self.org.refresh_from_db()
        self.assertEqual(self.org.plan_expires_at, end + timedelta(days=30))

    def test_switching_plan_starts_now(self):
        self.set_plan(self.pro, timezone.now() + timedelta(days=10))
        services.apply_paystack_result(self.pending(self.ent), {"status": "success", "amount": 3_000_000})
        self.org.refresh_from_db()
        self.assertEqual(self.org.plan, self.ent)
        self.assertAlmostEqual((self.org.plan_expires_at - timezone.now()).days, 29, delta=1)

    def test_webhook_requires_valid_signature(self):
        p = self.pending(self.pro)
        body = json.dumps({"event": "charge.success", "data": {
            "reference": p.reference, "status": "success", "amount": 1_000_000, "currency": "NGN"}}).encode()
        url = reverse("paystack_webhook")
        self.client.logout()
        bad = self.client.post(url, body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE="nope")
        self.assertEqual(bad.status_code, 400)
        sig = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
        ok = self.client.post(url, body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=sig)
        self.assertEqual(ok.status_code, 200)
        self.org.refresh_from_db()
        self.assertEqual(self.org.plan, self.pro)

    def test_checkout_redirects_to_paystack(self):
        with mock.patch.object(services, "_paystack", return_value={"authorization_url": "https://checkout.paystack.com/x"}) as api:
            resp = self.client.post(reverse("checkout", args=["professional"]))
        self.assertRedirects(resp, "https://checkout.paystack.com/x", fetch_redirect_response=False)
        payload = api.call_args.args[2]
        self.assertEqual(payload["amount"], 1_000_000)
        self.assertEqual(payload["email"], "boss@acme.test")

    def test_checkout_refused_when_over_target_plan_limit(self):
        for i in range(26):
            User.objects.create_user(username=f"ACME-{i + 2:04d}", password="x", organisation=self.org)
        self.set_plan(self.ent)
        with mock.patch.object(services, "_paystack") as api:
            resp = self.client.post(reverse("checkout", args=["professional"]))
        api.assert_not_called()
        self.assertRedirects(resp, reverse("billing"))

    def test_callback_verifies_with_paystack(self):
        p = self.pending(self.pro)
        with mock.patch.object(services, "_paystack", return_value={"status": "success", "amount": 1_000_000}):
            resp = self.client.get(reverse("paystack_callback") + f"?reference={p.reference}")
        self.assertRedirects(resp, reverse("billing"))
        self.org.refresh_from_db()
        self.assertEqual(self.org.plan, self.pro)

    @override_settings(PAYSTACK_SECRET_KEY="")
    def test_checkout_disabled_without_keys(self):
        with mock.patch.object(services, "_paystack") as api:
            self.client.post(reverse("checkout", args=["professional"]))
        api.assert_not_called()


class PlatformTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser(username="root", password="pw-123456", email="r@x.test")

    def test_superuser_lands_on_platform(self):
        self.client.force_login(self.su)
        self.assertRedirects(self.client.get(reverse("home")), reverse("platform"))

    def test_org_admin_cannot_open_platform(self):
        org = Organisation.objects.create(code="X", name="X")
        admin = User.objects.create_user(username="X-0001", password="x", organisation=org, role=User.ROLE_ADMIN)
        self.client.force_login(admin)
        self.assertRedirects(self.client.get(reverse("platform_plans")), reverse("home"), target_status_code=302)

    def test_change_price_and_features(self):
        self.client.force_login(self.su)
        pro = Plan.objects.get(slug="professional")
        feats = list(pro.features.values_list("pk", flat=True))[:3]
        resp = self.client.post(reverse("platform_plan_edit", args=[pro.pk]), {
            "name": "Professional", "tagline": "t", "price": 12500, "period_days": 30, "staff_limit": 40,
            "features": feats, "is_public": "on", "sort_order": 20})
        self.assertRedirects(resp, reverse("platform_plans"))
        pro.refresh_from_db()
        self.assertEqual((pro.price, pro.staff_limit, pro.features.count()), (12500, 40, 3))
        self.assertContains(self.client.get(reverse("pricing")), "12,500")

    def test_default_plan_must_stay_free(self):
        self.client.force_login(self.su)
        basic = Plan.objects.get(slug="basic")
        resp = self.client.post(reverse("platform_plan_edit", args=[basic.pk]), {
            "name": "Basic", "price": 500, "period_days": 30, "sort_order": 10})
        self.assertEqual(resp.status_code, 200)
        basic.refresh_from_db()
        self.assertEqual(basic.price, 0)

    def test_add_custom_feature_and_assign(self):
        self.client.force_login(self.su)
        ent = Plan.objects.get(slug="enterprise")
        self.client.post(reverse("platform_feature_add"), {
            "name": "Dedicated account manager", "description": "", "status": "live", "sort_order": 300,
            "plans": [ent.pk]})
        f = Feature.objects.get(name="Dedicated account manager")
        self.assertFalse(f.is_builtin)
        self.assertEqual(f.code, "dedicated_account_manager")
        self.assertIn(ent, f.plans.all())
        self.assertContains(self.client.get(reverse("pricing")), "Dedicated account manager")

    def test_builtin_feature_cannot_be_deleted(self):
        self.client.force_login(self.su)
        f = Feature.objects.get(code="qr_attendance")
        self.client.post(reverse("platform_feature_delete", args=[f.pk]))
        self.assertTrue(Feature.objects.filter(pk=f.pk).exists())

    def test_assign_plan_manually(self):
        self.client.force_login(self.su)
        org = Organisation.objects.create(code="Y", name="Y")
        ent = Plan.objects.get(slug="enterprise")
        self.client.post(reverse("platform_org", args=[org.pk]), {"plan": ent.pk, "plan_expires_at": ""})
        org.refresh_from_db()
        self.assertEqual(org.current_plan, ent)
        for name in ("platform", "platform_plans", "platform_features", "platform_payments"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_pricing_page_public(self):
        resp = self.client.get(reverse("pricing"))
        self.assertContains(resp, "Everything in Basic, plus")
        self.assertContains(resp, "10,000")
        self.assertContains(resp, "Face verification")
        self.assertNotContains(resp, "Coming soon")


class RegisterPlanTests(TestCase):
    def data(self, plan_slug=None, code="NEWCO"):
        d = {"org_name": "New Co", "org_type": "company", "code": code, "first_name": "Ada",
             "last_name": "Obi", "email": "ada@newco.test", "password1": "Strong-pass-9", "password2": "Strong-pass-9"}
        if plan_slug:
            d["plan"] = Plan.objects.get(slug=plan_slug).pk
        return d

    def test_plan_is_required(self):
        resp = self.client.post(reverse("register"), self.data())
        self.assertContains(resp, "Choose a plan to continue.")
        self.assertFalse(Organisation.objects.filter(code="NEWCO").exists())

    def test_nothing_preselected_without_query(self):
        self.assertNotContains(self.client.get(reverse("register")), "required checked")

    def test_pricing_link_preselects_plan(self):
        pro = Plan.objects.get(slug="professional")
        resp = self.client.get(reverse("register") + "?plan=professional")
        self.assertContains(resp, f'value="{pro.pk}" required checked')
        self.assertContains(self.client.get(reverse("pricing")), "?plan=professional")

    def test_free_plan_goes_to_dashboard(self):
        resp = self.client.post(reverse("register"), self.data("basic"))
        self.assertRedirects(resp, reverse("dashboard"))
        self.assertEqual(Organisation.objects.get(code="NEWCO").current_plan.slug, "basic")

    @override_settings(PAYSTACK_SECRET_KEY=SECRET)
    def test_paid_plan_goes_to_paystack(self):
        with mock.patch.object(services, "_paystack", return_value={"authorization_url": "https://checkout.paystack.com/y"}) as api:
            resp = self.client.post(reverse("register"), self.data("enterprise"))
        self.assertRedirects(resp, "https://checkout.paystack.com/y", fetch_redirect_response=False)
        self.assertEqual(api.call_args.args[2]["amount"], 3_000_000)
        org = Organisation.objects.get(code="NEWCO")
        self.assertEqual(org.current_plan.slug, "basic")  # until Paystack confirms
        self.assertEqual(org.payments.get().plan.slug, "enterprise")

    @override_settings(PAYSTACK_SECRET_KEY="")
    def test_paid_plan_without_paystack_lands_on_billing(self):
        resp = self.client.post(reverse("register"), self.data("professional"))
        self.assertRedirects(resp, reverse("billing"))

    def test_hidden_plan_cannot_be_chosen(self):
        Plan.objects.filter(slug="enterprise").update(is_public=False)
        resp = self.client.post(reverse("register"), self.data("enterprise"))
        self.assertContains(resp, "Choose one of the plans shown.")


class LandingPageTests(TestCase):
    def test_visitors_see_the_landing_page_with_live_prices(self):
        resp = self.client.get("/")
        self.assertContains(resp, "Clock in with")
        self.assertContains(resp, "10,000")
        self.assertContains(resp, "?plan=professional")

    def test_signed_in_users_skip_it(self):
        org = Organisation.objects.create(code="LP", name="LP")
        admin = User.objects.create_user(username="LP-0001", password="x", organisation=org, role=User.ROLE_ADMIN)
        self.client.force_login(admin)
        self.assertRedirects(self.client.get("/"), reverse("dashboard"))


class AuthPagesTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(code="TTC", name="Techmiary Technology Concepts")
        self.user = User.objects.create_user(username="TTC-0001", password="pw-123456", organisation=self.org,
                                             role=User.ROLE_ADMIN)

    def test_keep_me_signed_in(self):
        self.client.post(reverse("login"), {"username": "ttc-0001", "password": "pw-123456", "remember": "on"})
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.client.logout()
        self.client.post(reverse("login"), {"username": "TTC-0001", "password": "pw-123456"})
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_code_suggestions(self):
        from core.forms import suggest_code
        self.assertEqual(suggest_code("Techmiary Technology Concepts"), "TTC2")   # TTC is taken
        self.assertEqual(suggest_code("St. Mary's College of Jos"), "SMSCJ")
        self.assertEqual(suggest_code("Bethel"), "BETH")
        self.assertEqual(suggest_code("!!"), "")

    def test_live_code_check(self):
        url = reverse("register_check_code")
        taken = self.client.get(url, {"code": "ttc"}).json()
        self.assertEqual((taken["ok"], taken["suggestion"]), (False, "TTC2"))
        free = self.client.get(url, {"code": "abc", "name": "Alpha Beta Co"}).json()
        self.assertEqual((free["ok"], free["code"]), (True, "ABC"))
        self.assertEqual(self.client.get(url, {"name": "Grace Academy"}).json()["suggestion"], "GA")

    def test_register_reopens_the_step_with_the_problem(self):
        pro = Plan.objects.get(slug="professional")
        resp = self.client.post(reverse("register"), {"plan": pro.pk, "org_name": "X", "org_type": "company",
                                                      "code": "TTC", "first_name": "A", "last_name": "B",
                                                      "email": "a@b.test", "password1": "pw-123456", "password2": "pw-123456"})
        self.assertContains(resp, 'data-error-step="2"')
        self.assertContains(resp, "TTC is already taken. Try TTC2.")
        resp = self.client.post(reverse("register"), {"plan": pro.pk, "org_name": "X", "org_type": "company",
                                                      "code": "XYZ", "first_name": "A", "last_name": "B",
                                                      "email": "a@b.test", "password1": "pw-123456", "password2": "nope"})
        self.assertContains(resp, 'data-error-step="3"')

    def test_pages_render(self):
        self.assertContains(self.client.get(reverse("login")), "Keep me signed in")
        self.assertContains(self.client.get(reverse("register")), "af-steps")


class DeleteAccountPageTests(TestCase):
    def test_public_page_and_request(self):
        from django.urls import reverse
        from billing.models import ContactMessage
        page = self.client.get(reverse("delete_account"))
        self.assertContains(page, "What we delete")
        self.assertContains(page, "What we keep")
        r = self.client.post(reverse("delete_account"), {"scope": "me", "name": "Ada Obi", "organisation": "Org",
                                                          "sign_in_id": "ORG-0004", "email": "ada@example.com"})
        self.assertRedirects(r, reverse("delete_account"))
        msg = ContactMessage.objects.get()
        self.assertIn("ACCOUNT DELETION REQUEST", msg.message)
        self.assertIn("ORG-0004", msg.message)

    def test_needs_a_way_to_reply(self):
        from django.urls import reverse
        r = self.client.post(reverse("delete_account"), {"scope": "org", "name": "A", "organisation": "Org"})
        self.assertContains(r, "Leave an email address or a phone number")


@override_settings(EMAIL_HOST="smtp.example.com", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AdminEmailTests(TestCase):
    def setUp(self):
        from core.models import Organisation, User
        self.org = Organisation.objects.create(code="EM", name="Email Org")
        self.admin = User.objects.create_user(username="EM-0001", password="x", organisation=self.org,
                                              role=User.ROLE_ADMIN, first_name="Ada", email="ada@example.com")

    def test_welcome_mentions_id_and_plans(self):
        from django.core import mail
        from billing.emails import welcome
        self.assertTrue(welcome(self.org, self.admin))
        body = mail.outbox[0].body
        self.assertIn("EM-0001", body)
        self.assertIn("/pricing/", body)

    def test_nudge_at_most_every_14_days(self):
        from django.core import mail
        from billing.emails import upgrade_nudge
        self.assertTrue(upgrade_nudge(self.org, self.admin, "staff_limit"))
        self.assertFalse(upgrade_nudge(self.org, self.admin, "feature", Feature.objects.first().code))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/manage/billing/", mail.outbox[0].body)

    def test_only_administrators_get_nudged(self):
        from core.models import User
        from billing.emails import upgrade_nudge
        staff = User.objects.create_user(username="EM-0002", password="x", organisation=self.org, email="s@example.com")
        self.assertFalse(upgrade_nudge(self.org, staff, "staff_limit"))

    @override_settings(EMAIL_HOST="")
    def test_nothing_without_an_email_account(self):
        from billing.emails import upgrade_nudge, welcome
        self.assertFalse(welcome(self.org, self.admin))
        self.assertFalse(upgrade_nudge(self.org, self.admin, "staff_limit"))

    def test_sign_up_sends_the_welcome(self):
        from django.core import mail
        plan = Plan.objects.filter(is_public=True, price=0).first()
        r = self.client.post(reverse("register"), {
            "plan": plan.pk, "org_name": "Signup School", "org_type": "school", "code": "SGS",
            "first_name": "Bola", "last_name": "Ade", "email": "bola@example.com",
            "password1": "a-Strong-pass-123", "password2": "a-Strong-pass-123"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(any(m.to == ["bola@example.com"] and "Welcome" in m.subject for m in mail.outbox))
