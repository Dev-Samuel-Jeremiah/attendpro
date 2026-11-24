from datetime import datetime, time
from unittest import mock

from django.test import RequestFactory, TestCase
from django.utils import timezone

from billing.models import Plan
from core import services
from core.models import AttendanceRecord, Organisation, ScanLog, User


def at(hour, minute=0):
    """An aware datetime today (in the project time zone) at the given local time."""
    return timezone.make_aware(datetime.combine(timezone.localdate(), time(hour, minute)))


class CheckInClosesAtWorkEndTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(code="TST", name="Test Org", org_type="school",
                                               work_start=time(8, 0), work_end=time(16, 0),
                                               plan=Plan.objects.get(slug="professional"))
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


class LocationClockTests(TestCase):
    """The clock-in button (Basic plan and up)."""
    LAT, LNG = 9.896500, 8.858300

    def setUp(self):
        self.org = Organisation.objects.create(code="LOC", name="Loc Org", work_start=time(8, 0),
                                               work_end=time(16, 0), latitude=self.LAT, longitude=self.LNG,
                                               location_radius_m=100)  # no plan = Basic
        self.user = User.objects.create_user(username="LOC-0002", password="x", organisation=self.org)
        self.request = RequestFactory().post("/api/clock/")

    def clock(self, lat, lng, accuracy=10, when=None):
        with mock.patch("django.utils.timezone.now", return_value=when or at(9, 0)):
            return services.clock_by_location(self.user, self.request, lat, lng, accuracy)

    def test_inside_radius_checks_in(self):
        result = self.clock(self.LAT + 0.0005, self.LNG)  # about 55 m north
        self.assertEqual(result.action, "check_in")
        rec = AttendanceRecord.objects.get(user=self.user)
        self.assertEqual(rec.source, "location")
        self.assertEqual(rec.status, "late")  # 09:00 is after 08:10
        log = ScanLog.objects.get(user=self.user)
        self.assertTrue(40 <= log.distance_m <= 70)

    def test_outside_radius_is_rejected_and_logged(self):
        result = self.clock(self.LAT + 0.01, self.LNG)  # about 1.1 km
        self.assertFalse(result.ok)
        self.assertIn("1.1 km from Loc Org", result.message)
        self.assertFalse(AttendanceRecord.objects.exists())
        self.assertEqual(ScanLog.objects.get(user=self.user).action, "rejected")

    def test_accuracy_allowance_is_capped(self):
        # 140 m away with ±200 m accuracy: allowance capped at 50 m, so 90 m > radius? 140-50 = 90 ≤ 100 → ok
        self.assertEqual(self.clock(self.LAT + 0.00126, self.LNG, accuracy=200).action, "check_in")

    def test_far_with_poor_accuracy_still_rejected(self):
        self.assertFalse(self.clock(self.LAT + 0.002, self.LNG, accuracy=250).ok)  # ~220 m

    def test_imprecise_location_rejected(self):
        result = self.clock(self.LAT, self.LNG, accuracy=1500)
        self.assertFalse(result.ok)
        self.assertIn("precise", result.title)

    def test_big_site_accepts_a_rough_cell_tower_reading(self):
        # A 1 km site: a phone that only gets a ±600 m cell-tower position 439 m away can clock in...
        self.org.location_radius_m = 1000
        self.org.save()
        self.assertEqual(self.clock(self.LAT + 0.00395, self.LNG, accuracy=600).action, "check_in")
        self.assertEqual(services.locate_good_enough(self.user), 600)

    def test_rough_reading_still_refused_at_a_small_site(self):
        # ...but at a 100 m site the same reading is too rough to tell.
        result = self.clock(self.LAT + 0.0005, self.LNG, accuracy=600)
        self.assertEqual(result.title, "Location not precise enough")
        self.assertEqual(services.locate_good_enough(self.user), 60)

    def test_imprecise_location_explains_where_to_turn_on_precise_location(self):
        self.request = RequestFactory(HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14) AttendProApp/android").post("/")
        msg = self.clock(self.LAT, self.LNG, accuracy=2000).message
        self.assertIn("2000 m", msg)
        self.assertIn("Apps → AttendPro", msg)
        self.request = RequestFactory(HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Safari").post("/")
        self.assertIn("Safari Websites", self.clock(self.LAT, self.LNG, accuracy=2000).message)

    def test_no_location_set(self):
        self.org.latitude = self.org.longitude = None
        self.org.save()
        self.assertEqual(self.clock(self.LAT, self.LNG).title, "Location not set up")

    def test_bad_input(self):
        self.assertEqual(self.clock("abc", None).title, "Location not received")
        self.assertEqual(self.clock(200, 8).title, "Location not received")

    def test_second_press_checks_out_and_closing_time_applies(self):
        self.clock(self.LAT, self.LNG, when=at(8, 0))
        self.assertEqual(self.clock(self.LAT, self.LNG, when=at(17, 0)).action, "check_out")
        other = User.objects.create_user(username="LOC-0003", password="x", organisation=self.org)
        self.user = other
        self.assertEqual(self.clock(self.LAT, self.LNG, when=at(16, 30)).title, "Check-in is closed for today")

    def test_basic_plan_cannot_use_qr(self):
        result = services.mark_attendance(self.user, "", self.request, verified_org=self.org)
        self.assertFalse(result.ok)
        self.assertIn("QR attendance", result.title)

    def test_distance_formula(self):
        # One degree of latitude is about 111.2 km
        self.assertAlmostEqual(services.distance_m(0, 0, 1, 0) / 1000, 111.19, places=1)
