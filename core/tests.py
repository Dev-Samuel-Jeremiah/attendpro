from datetime import datetime, time
from unittest import mock

from django.test import RequestFactory, TestCase
from django.utils import timezone

from core import services
from core.models import AttendanceRecord, Organisation, ScanLog, User


def at(hour, minute=0):
    """An aware datetime today (in the project time zone) at the given local time."""
    return timezone.make_aware(datetime.combine(timezone.localdate(), time(hour, minute)))


class CheckInClosesAtWorkEndTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(code="TST", name="Test Org", org_type="school",
                                               work_start=time(8, 0), work_end=time(16, 0))
        self.user = User.objects.create_user(username="TST-0002", password="x", first_name="A",
                                             last_name="B", organisation=self.org)
        self.request = RequestFactory().get("/scan/")

    def scan(self, when):
        with mock.patch("django.utils.timezone.now", return_value=when):
            return services.mark_attendance(self.user, "", self.request, verified_org=self.org)

    def test_check_in_allowed_before_work_end(self):
        result = self.scan(at(15, 59))
        self.assertEqual(result.action, "check_in")

    def test_check_in_refused_after_work_end(self):
        result = self.scan(at(16, 0))
        self.assertFalse(result.ok)
        self.assertEqual(result.action, "rejected")
        self.assertFalse(AttendanceRecord.objects.filter(user=self.user).exists())
        self.assertTrue(ScanLog.objects.filter(user=self.user, action="rejected").exists())

    def test_check_out_still_allowed_after_work_end(self):
        self.scan(at(8, 0))
        result = self.scan(at(17, 30))
        self.assertEqual(result.action, "check_out")

    def test_overnight_shift_not_blocked(self):
        self.org.work_start, self.org.work_end = time(22, 0), time(6, 0)
        self.org.save()
        result = self.scan(at(23, 0))
        self.assertEqual(result.action, "check_in")
