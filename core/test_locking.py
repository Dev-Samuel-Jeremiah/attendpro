from datetime import datetime, time

from django.contrib.admin.sites import site
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Plan
from core.models import AttendanceRecord, Organisation, User
from recovery import services as recovery


class ScannedAttendanceIsLockedTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(code="LK", name="Lock", plan=Plan.objects.get(slug="enterprise"))
        self.admin = User.objects.create_user(username="LK-0001", password="x", organisation=self.org,
                                              role=User.ROLE_ADMIN)
        self.staff = User.objects.create_user(username="LK-0002", password="x", organisation=self.org, first_name="Ada")
        self.day = timezone.localdate()
        self.cin = timezone.make_aware(datetime.combine(self.day, time(8, 40)))
        self.rec = AttendanceRecord.objects.create(organisation=self.org, user=self.staff, date=self.day,
                                                   check_in=self.cin, status="late", source="qr")
        self.client.force_login(self.admin)

    def test_times_and_status_cannot_be_changed(self):
        url = reverse("record_edit", args=[self.rec.pk])
        page = self.client.get(url)
        self.assertContains(page, "can't be changed or deleted")
        self.assertNotContains(page, 'name="check_in_time"')
        self.client.post(url, {"note": "Bus broke down", "status": "present", "check_in_time": "07:55",
                               "user": self.staff.pk, "date": self.day})
        self.rec.refresh_from_db()
        self.assertEqual((self.rec.check_in, self.rec.status, self.rec.note), (self.cin, "late", "Bus broke down"))

    def test_cannot_be_deleted(self):
        self.client.post(reverse("record_edit", args=[self.rec.pk]), {"delete": "1"})
        self.assertTrue(AttendanceRecord.objects.filter(pk=self.rec.pk).exists())
        with self.assertRaises(PermissionError):
            recovery.trash(self.rec, self.admin)

    def test_manual_entries_have_no_times_and_cannot_claim_presence(self):
        other = User.objects.create_user(username="LK-0003", password="x", organisation=self.org)
        self.client.post(reverse("record_add"), {"user": other.pk, "date": self.day, "status": "present",
                                                 "check_in_time": "08:00"})
        self.assertFalse(AttendanceRecord.objects.filter(user=other).exists())          # "present" refused
        self.client.post(reverse("record_add"), {"user": other.pk, "date": self.day, "status": "leave",
                                                 "check_in_time": "08:00", "note": "Hospital"})
        rec = AttendanceRecord.objects.get(user=other)
        self.assertEqual((rec.status, rec.check_in, rec.source), ("leave", None, "manual"))

    def test_cannot_overwrite_a_scanned_day(self):
        resp = self.client.post(reverse("record_add"), {"user": self.staff.pk, "date": self.day, "status": "absent"})
        self.assertContains(resp, "already has attendance")
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.status, "late")

    def test_django_admin_is_read_only(self):
        ma = site._registry[AttendanceRecord]
        req = RequestFactory().get("/")
        req.user = User.objects.create_superuser("root", "r@x.test", "pw-123456")
        self.assertIn("check_in", ma.get_readonly_fields(req, self.rec))
        self.assertFalse(ma.has_delete_permission(req, self.rec))
        self.assertFalse(ma.has_add_permission(req))
        self.assertNotIn("delete_selected", ma.get_actions(req))

    def test_the_person_can_still_check_out_by_scanning(self):
        from core import services
        later = timezone.make_aware(datetime.combine(self.day, time(17)))
        from unittest import mock
        with mock.patch("django.utils.timezone.now", return_value=later):
            r = services.record_attendance(self.staff, self.org, RequestFactory().post("/"), source="qr")
        self.assertEqual(r.action, "check_out")
