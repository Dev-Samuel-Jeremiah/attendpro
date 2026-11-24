from datetime import datetime, time
from unittest import mock

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Plan
from core import services
from core.models import Organisation, User

HQ = (9.8965, 8.8583)


class AttendanceMethodTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(code="AM", name="Method Org", plan=Plan.objects.get(slug="professional"),
                                               latitude=HQ[0], longitude=HQ[1], work_start=time(8), work_end=time(23, 59))
        self.admin = User.objects.create_user(username="AM-0001", password="x", organisation=self.org, role=User.ROLE_ADMIN)
        self.staff = User.objects.create_user(username="AM-0002", password="x", organisation=self.org)
        self.rf = RequestFactory().post("/")
        self.at9 = timezone.make_aware(datetime.combine(timezone.localdate(), time(9)))

    def use(self, method):
        self.org.attendance_method = method
        self.org.save()
        self.staff.organisation = self.org

    def button(self):
        with mock.patch("django.utils.timezone.now", return_value=self.at9):
            return services.clock_by_location(self.staff, self.rf, HQ[0], HQ[1], 10)

    def qr(self):
        with mock.patch("django.utils.timezone.now", return_value=self.at9):
            return services.mark_attendance(self.staff, "", self.rf, verified_org=self.org)

    def test_both_by_default(self):
        self.assertTrue(self.org.offers_method_choice and self.org.uses_button and self.org.uses_qr)
        self.assertEqual(self.button().action, "check_in")

    def test_button_only(self):
        self.use("button")
        self.assertEqual(self.qr().title, "Use the Clock in button")
        self.assertEqual(self.button().action, "check_in")
        self.client.force_login(self.staff)
        self.assertRedirects(self.client.get(reverse("scanner")), reverse("portal"))
        page = self.client.get(reverse("portal")).content.decode()
        self.assertIn('id="clock"', page)
        self.assertNotIn("Scan QR to check in", page)
        self.assertEqual(self.client.get(reverse("kiosk_token", args=[self.org.kiosk_key])).status_code, 403)
        self.assertContains(self.client.get(reverse("kiosk", args=[self.org.kiosk_key])), "Clock in</b> button on each person")

    def test_qr_only(self):
        self.use("qr")
        self.assertEqual(self.button().title, "Scan the QR code instead")
        self.assertEqual(self.qr().action, "check_in")
        self.client.force_login(self.staff)
        page = self.client.get(reverse("portal")).content.decode()
        self.assertNotIn('id="clock"', page)
        self.assertIn("Scan QR to check", page)

    def test_basic_has_no_choice(self):
        self.org.plan = Plan.objects.get(slug="basic")
        self.use("qr")  # a leftover setting can't switch Basic's only method off
        self.org.forget_plan()
        self.assertFalse(self.org.offers_method_choice)
        self.assertTrue(self.org.uses_button)
        self.assertFalse(self.org.uses_qr)
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("org_settings")), 'name="attendance_method"')

    def test_admin_chooses_in_settings(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("org_settings"))
        self.assertContains(page, "How people record attendance")
        form = page.context["form"]
        data = {k: v for k, v in form.initial.items() if v is not None and k not in ("logo", "working_days")}
        data.update({"working_days_choice": ["0", "1", "2", "3", "4"], "attendance_method": "qr",
                     "work_start": "08:00", "work_end": "16:00"})
        for b in ("notify_late", "notify_absent", "notify_checkout", "email_notifications"):
            data[b] = "on"
        resp = self.client.post(reverse("org_settings"), data)
        self.assertEqual(resp.status_code, 302, resp.context["form"].errors if resp.context else "")
        self.org.refresh_from_db()
        self.assertEqual(self.org.attendance_method, "qr")
