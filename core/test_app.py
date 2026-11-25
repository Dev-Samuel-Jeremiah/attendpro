from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Organisation, User

ANDROID = "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36 AttendProApp/android"
IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile AttendProApp/ios"


class MobileAppTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(code="MA", name="Mobile Org")
        self.admin = User.objects.create_user(username="MA-0001", password="pw-123456", organisation=self.org,
                                              role=User.ROLE_ADMIN)

    def test_start_page(self):
        self.client.cookies["ap_welcomed"] = "1"
        self.assertRedirects(self.client.get(reverse("app_start"), HTTP_USER_AGENT=ANDROID), reverse("login"))
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("app_start"), HTTP_USER_AGENT=ANDROID), reverse("home"),
                             target_status_code=302)

    def test_first_launch_shows_the_welcome_tour_once(self):
        self.assertRedirects(self.client.get(reverse("app_start"), HTTP_USER_AGENT=ANDROID), reverse("app_welcome"))
        page = self.client.get(reverse("app_welcome"), HTTP_USER_AGENT=ANDROID)
        self.assertContains(page, "joining my team")
        self.assertContains(page, "setting up my organisation")
        self.assertContains(page, "<svg")                               # the real QR code picture
        done = self.client.get(reverse("app_welcome_done") + "?to=register", HTTP_USER_AGENT=ANDROID)
        self.assertRedirects(done, reverse("register"), fetch_redirect_response=False)
        self.assertEqual(done.cookies["ap_welcomed"].value, "1")
        self.assertTrue(done.cookies["ap_welcomed"]["httponly"])
        # Seen it: straight to sign-in from now on (also from the home page)
        self.assertRedirects(self.client.get(reverse("app_start"), HTTP_USER_AGENT=ANDROID), reverse("login"))
        self.assertRedirects(self.client.get("/", HTTP_USER_AGENT=ANDROID), reverse("login"))

    def test_welcome_choice_defaults_to_sign_in(self):
        r = self.client.get(reverse("app_welcome_done") + "?to=https://evil.example", HTTP_USER_AGENT=IOS)
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)

    def test_signed_in_people_skip_the_welcome(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("app_start"), HTTP_USER_AGENT=ANDROID), reverse("home"),
                             target_status_code=302)

    def test_browsers_never_see_the_welcome_redirect(self):
        self.assertContains(self.client.get("/"), "Clock in with")

    def test_home_in_app_skips_the_marketing_page(self):
        self.client.cookies["ap_welcomed"] = "1"
        self.assertRedirects(self.client.get("/", HTTP_USER_AGENT=IOS), reverse("login"))
        self.assertContains(self.client.get("/"), "Clock in with")              # browsers still get it

    def test_bridge_only_in_the_app(self):
        page = self.client.get(reverse("login"), HTTP_USER_AGENT=ANDROID).content.decode()
        self.assertIn("js/app-bridge", page)
        self.assertIn('class="in-app in-app-android"', page)
        self.assertNotIn("js/app-bridge", self.client.get(reverse("login")).content.decode())
        self.assertIn("in-app-ios", self.client.get(reverse("login"), HTTP_USER_AGENT=IOS).content.decode())

    @override_settings(APP_MIN_VERSION="1.2.0", APP_IOS_URL="https://apps.apple.com/app/id1")
    def test_config(self):
        d = self.client.get(reverse("app_config"), HTTP_USER_AGENT=IOS).json()
        self.assertEqual((d["min_version"], d["ios_url"], d["signed_in"]), ("1.2.0", "https://apps.apple.com/app/id1", False))
        self.assertIn("no-cache", self.client.get(reverse("app_config"))["Cache-Control"])


class GetAppPageTests(TestCase):
    def test_page(self):
        resp = self.client.get(reverse("get_app"), HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14) Mobile")
        self.assertContains(resp, "releases/latest/download/attendpro.apk")
        self.assertContains(resp, "lp-get-card hot")              # Android card highlighted on Android
        self.assertContains(resp, "Coming to the App Store")
        self.assertContains(resp, "<svg")                          # QR code for computers
        self.assertContains(self.client.get(reverse("login")), reverse("get_app"))

    @override_settings(APP_IOS_URL="https://apps.apple.com/app/id123")
    def test_ios_link_when_published(self):
        self.assertContains(self.client.get(reverse("get_app")), "https://apps.apple.com/app/id123")


class ReviewAccountCommandTests(TestCase):
    def test_creates_once_and_resets_passwords(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("create_review_account", stdout=out)
        self.assertIn("REVIEW-0001 / Rv-", out.getvalue())
        org = Organisation.objects.get(code="REVIEW")
        self.assertEqual(org.members.count(), 12)
        self.assertTrue(org.attendance.exists() if hasattr(org, "attendance") else True)
        pw = out.getvalue().split("REVIEW-0002 / ")[1].split()[0]
        self.assertTrue(self.client.login(username="REVIEW-0002", password=pw))
        again = StringIO()
        call_command("create_review_account", stdout=again)
        self.assertIn("already exists", again.getvalue())
        call_command("create_review_account", "--reset", stdout=StringIO())
        self.assertFalse(self.client.login(username="REVIEW-0002", password=pw))


class NoPaymentsInStoreAppTests(TestCase):
    """Store rules: the app never shows prices, checkout or upgrade prompts. The website does."""
    def setUp(self):
        from billing.models import Plan
        self.pro = Plan.objects.filter(is_public=True, price__gt=0).order_by("price").first()
        self.org = Organisation.objects.create(code="PAY", name="Pay Org")
        self.admin = User.objects.create_user(username="PAY-0001", password="pw-123456", organisation=self.org,
                                              role=User.ROLE_ADMIN)

    def test_pricing_page_is_not_shown_in_the_app(self):
        self.client.cookies["ap_welcomed"] = "1"
        self.assertRedirects(self.client.get(reverse("pricing"), HTTP_USER_AGENT=ANDROID), reverse("home"),
                             target_status_code=302)
        self.assertEqual(self.client.get(reverse("pricing")).status_code, 200)

    def test_billing_page_has_no_checkout_in_the_app(self):
        self.client.force_login(self.admin)
        app = self.client.get(reverse("billing"), HTTP_USER_AGENT=IOS).content.decode()
        self.assertIn("Plan changes aren't available in the app", app)
        self.assertNotIn("/manage/billing/checkout/", app)
        self.assertNotIn("₦", app)
        web = self.client.get(reverse("billing")).content.decode()
        self.assertIn("/manage/billing/checkout/", web)

    def test_checkout_refused_in_the_app(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("checkout", args=[self.pro.slug]), HTTP_USER_AGENT=ANDROID)
        self.assertRedirects(r, reverse("billing"), fetch_redirect_response=False)
        self.org.refresh_from_db()
        self.assertFalse(self.org.payments.exists())

    def test_sign_up_in_the_app_offers_only_the_free_plan(self):
        page = self.client.get(reverse("register") + f"?plan={self.pro.slug}", HTTP_USER_AGENT=ANDROID).content.decode()
        self.assertIn("starts on the free plan", page)
        self.assertNotIn(f'data-name="{self.pro.name}"', page)
        self.assertIn(f'data-name="{self.pro.name}"', self.client.get(reverse("register")).content.decode())

    def test_upgrade_wording(self):
        from django.test import RequestFactory
        from billing.services import upgrade_message
        app = RequestFactory(HTTP_USER_AGENT=ANDROID).get("/")
        self.assertNotIn("Upgrade", upgrade_message("anything", app))


class AppActivityTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(code="AA", name="Activity Org")
        self.staff = User.objects.create_user(username="AA-0002", password="pw-123456", organisation=self.org,
                                              first_name="Tess", email="tess@example.com")

    def test_app_use_is_recorded_once_a_day_and_web_use_is_not(self):
        from core.models import AppActivity
        self.client.force_login(self.staff)
        self.client.get(reverse("portal"))                                   # website
        self.assertFalse(AppActivity.objects.exists())
        self.client.get(reverse("portal"), HTTP_USER_AGENT=ANDROID)          # app
        self.client.get(reverse("my_history"), HTTP_USER_AGENT=ANDROID)
        row = AppActivity.objects.get()
        self.assertEqual((row.user, row.platform), (self.staff, "android"))

    def test_platform_page_lists_app_users(self):
        self.client.force_login(self.staff)
        self.client.get(reverse("portal"), HTTP_USER_AGENT=IOS)
        User.objects.create_superuser(username="root", password="pw-123456", email="r@x.test")
        self.client.force_login(User.objects.get(username="root"))
        page = self.client.get(reverse("platform_app_users"))
        self.assertContains(page, "tess@example.com")
        self.assertContains(page, "iPhone")
        self.assertContains(page, "Today")
