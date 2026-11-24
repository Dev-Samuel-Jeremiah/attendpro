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
        self.assertRedirects(self.client.get(reverse("app_start"), HTTP_USER_AGENT=ANDROID), reverse("login"))
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("app_start"), HTTP_USER_AGENT=ANDROID), reverse("home"),
                             target_status_code=302)

    def test_home_in_app_skips_the_marketing_page(self):
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
