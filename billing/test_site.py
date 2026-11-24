from django.test import TestCase, override_settings
from django.core import mail
from django.urls import reverse

from billing.models import ContactMessage, Feature, SiteSettings, Testimonial
from core.models import User


class PublicSiteTests(TestCase):
    def test_legal_and_contact_pages(self):
        for name, text in (("privacy", "Nigeria Data Protection Act 2023"), ("terms", "full refund within 7 days"),
                           ("contact", "Send us a message"), ("pricing", "Does it renew automatically?")):
            resp = self.client.get(reverse(name))
            self.assertContains(resp, text, msg_prefix=name)
            self.assertContains(resp, reverse("privacy"))      # footer links everywhere
        home = self.client.get("/")
        self.assertContains(home, reverse("terms"))
        self.assertContains(home, "Questions before you start?")

    def test_contact_details_appear_once_set(self):
        self.assertNotContains(self.client.get("/"), "wa.me/")
        s = SiteSettings.load()
        s.whatsapp, s.sales_email, s.address = "+234 803 123 4567", "sales@attendpro.cloud", "Rayfield, Jos"
        s.save()
        home = self.client.get("/").content.decode()
        self.assertIn("https://wa.me/2348031234567", home)
        self.assertIn("mailto:sales@attendpro.cloud", home)
        self.assertIn("Rayfield, Jos", self.client.get(reverse("contact")).content.decode())
        self.assertIn("sales@attendpro.cloud", self.client.get(reverse("terms")).content.decode())

    @override_settings(EMAIL_HOST="smtp.test", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_contact_form(self):
        SiteSettings.objects.create(sales_email="sales@attendpro.cloud")
        url = reverse("contact")
        bad = self.client.post(url, {"name": "Ada", "message": "Hi"})
        self.assertContains(bad, "Leave an email address or a phone number")
        self.client.post(url, {"name": "Ada", "organisation": "Grace Academy", "email": "ada@grace.test",
                               "staff_count": "45", "message": "We'd like a demo."})
        msg = ContactMessage.objects.get()
        self.assertEqual((msg.organisation, msg.staff_count), ("Grace Academy", "45"))
        self.assertEqual(mail.outbox[0].to, ["sales@attendpro.cloud"])
        self.assertEqual(mail.outbox[0].reply_to, ["ada@grace.test"])
        self.client.post(url, {"name": "Bot", "email": "b@b.test", "message": "spam", "website": "http://x"})
        self.assertEqual(ContactMessage.objects.count(), 1)                    # spam trap
        for i in range(6):
            self.client.post(url, {"name": f"P{i}", "phone": "0803", "message": "again"})
        self.assertEqual(ContactMessage.objects.count(), 5)                    # 5 an hour per sender

    def test_quotes_only_when_published(self):
        t = Testimonial.objects.create(quote="Attendance takes care of itself now.", name="Mrs Okafor",
                                       role="Principal", organisation="Grace Academy")
        self.assertNotContains(self.client.get("/"), "Attendance takes care of itself now.")
        t.is_published = True
        t.save()
        self.assertContains(self.client.get("/"), "Attendance takes care of itself now.")

    def test_consistent_feature_names_and_single_industry_list(self):
        names = dict(Feature.objects.values_list("code", "name"))
        self.assertEqual(names["manual_clock"], "GPS clock-in button")
        self.assertEqual(names["geofencing"], "GPS on QR scans and branch geofences")
        self.assertEqual(names["exports"], "Excel, CSV and PDF export")
        home = self.client.get("/").content.decode()
        self.assertEqual(home.count("Hotels &amp; restaurants"), 1)
        self.assertIn("<title>AttendPro: clock in with one tap, know who's in live</title>", home)
        self.assertIn('content="AttendPro: clock in with one tap, know who\'s in live"', home)

    def test_platform_manages_site(self):
        su = User.objects.create_superuser("root", "r@x.test", "pw-123456")
        self.client.force_login(su)
        self.client.post(reverse("platform_site"), {"company_name": "Techmiary Technology Concepts",
                                                    "sales_email": "sales@x.test", "whatsapp": "+2348000000000"})
        self.assertEqual(SiteSettings.load().whatsapp, "+2348000000000")
        for name in ("platform_site", "platform_messages", "platform_testimonials", "platform_testimonial_add"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.client.post(reverse("platform_testimonial_add"), {"quote": "Great", "name": "A", "organisation": "B",
                                                               "is_published": "on", "sort_order": 1})
        self.assertTrue(Testimonial.objects.filter(is_published=True).exists())
