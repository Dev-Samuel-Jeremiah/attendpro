from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing import services
from billing.models import Payment, Plan
from core.models import Organisation, User

SECRET = "sk_test_dummy"


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
class YearlyBillingTests(TestCase):
    def setUp(self):
        self.pro = Plan.objects.get(slug="professional")
        self.org = Organisation.objects.create(code="YR", name="Yearly Org", email="o@y.test")
        self.admin = User.objects.create_user(username="YR-0001", password="x", organisation=self.org,
                                              role=User.ROLE_ADMIN, email="a@y.test")
        self.client.force_login(self.admin)

    def checkout(self, cycle):
        with mock.patch.object(services, "_paystack", return_value={"authorization_url": "https://checkout.paystack.com/z"}) as api:
            self.client.post(reverse("checkout", args=["professional"]), {"cycle": cycle})
        return api.call_args.args[2], Payment.objects.latest("created_at")

    def test_defaults_are_ten_months(self):
        self.assertEqual((self.pro.yearly_price, self.pro.yearly_saving), (100000, 20000))
        self.assertEqual(Plan.objects.get(slug="enterprise").yearly_price, 300000)
        self.assertFalse(Plan.objects.get(slug="basic").has_yearly)

    def test_yearly_checkout_charges_the_yearly_price_and_lasts_a_year(self):
        payload, p = self.checkout("yearly")
        self.assertEqual((payload["amount"], payload["metadata"]["cycle"]), (10_000_000, "yearly"))
        self.assertEqual(p.cycle, "yearly")
        services.apply_paystack_result(p, {"status": "success", "amount": 10_000_000, "currency": "NGN"})
        self.org.refresh_from_db()
        self.assertAlmostEqual((self.org.plan_expires_at - timezone.now()).days, 364, delta=1)
        # renewing early adds another year on top
        _, p2 = self.checkout("yearly")
        end = self.org.plan_expires_at
        services.apply_paystack_result(p2, {"status": "success", "amount": 10_000_000, "currency": "NGN"})
        self.org.refresh_from_db()
        self.assertEqual(self.org.plan_expires_at, end + timedelta(days=365))

    def test_monthly_is_the_default_and_unknown_cycles_fall_back(self):
        payload, p = self.checkout("weekly")
        self.assertEqual((payload["amount"], p.cycle), (1_000_000, "monthly"))

    def test_plan_without_yearly_price_bills_monthly(self):
        self.pro.yearly_price = None
        self.pro.save()
        payload, p = self.checkout("yearly")
        self.assertEqual((payload["amount"], p.cycle), (1_000_000, "monthly"))

    def test_register_with_yearly(self):
        self.client.logout()
        with mock.patch.object(services, "_paystack", return_value={"authorization_url": "https://checkout.paystack.com/r"}) as api:
            self.client.post(reverse("register"), {
                "plan": self.pro.pk, "cycle": "yearly", "org_name": "New", "org_type": "company", "code": "NEWY",
                "first_name": "A", "last_name": "B", "email": "a@new.test", "password1": "pw-123456", "password2": "pw-123456"})
        self.assertEqual(api.call_args.args[2]["amount"], 10_000_000)

    def test_pages_show_both_prices(self):
        page = self.client.get(reverse("pricing") + "?cycle=yearly").content.decode()
        self.assertIn('data-cycle="yearly"', page)
        self.assertIn("₦100,000", page)
        self.assertIn("save ₦20,000", page)
        self.assertIn('name="cycle"', self.client.get(reverse("billing")).content.decode())
        self.client.logout()
        self.assertIn('id="af-cycle"', self.client.get(reverse("register") + "?plan=professional&cycle=yearly").content.decode())

    def test_platform_sets_yearly_price(self):
        su = User.objects.create_superuser("root", "r@x.test", "pw-123456")
        self.client.force_login(su)
        self.client.post(reverse("platform_plan_edit", args=[self.pro.pk]), {
            "name": "Professional", "price": 10000, "yearly_price": 96000, "period_days": 30, "staff_limit": 25,
            "features": list(self.pro.features.values_list("pk", flat=True)), "is_public": "on", "sort_order": 20})
        self.pro.refresh_from_db()
        self.assertEqual(self.pro.yearly_price, 96000)
        basic = Plan.objects.get(slug="basic")
        resp = self.client.post(reverse("platform_plan_edit", args=[basic.pk]), {
            "name": "Basic", "price": 0, "yearly_price": 5000, "period_days": 30, "sort_order": 10})
        self.assertEqual(resp.status_code, 200)
        basic.refresh_from_db()
        self.assertIsNone(basic.yearly_price)
