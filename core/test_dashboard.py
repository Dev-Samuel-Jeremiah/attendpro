from datetime import datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.dashboard import admin_dashboard, staff_home
from core.models import AttendanceRecord, Department, Organisation, User


class DashboardTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(code="DSH", name="Dash Org", work_start=time(8, 0),
                                               work_end=time(23, 59), grace_minutes=10,
                                               working_days="0,1,2,3,4,5,6", latitude=9.9, longitude=8.9)
        dept = Department.objects.create(organisation=self.org, name="ICT")
        self.admin = User.objects.create_user(username="DSH-0001", password="pw-123456", organisation=self.org,
                                              role=User.ROLE_ADMIN, first_name="Ada")
        self.staff = [User.objects.create_user(username=f"DSH-00{i:02d}", password="x", organisation=self.org,
                                               first_name=f"Person{i}", department=dept) for i in range(2, 6)]
        today = timezone.localdate()
        tz = timezone.get_current_timezone()
        for days_ago in range(0, 6):
            d = today - timedelta(days=days_ago)
            for n, u in enumerate(self.staff[:3]):
                late = n == 2
                when = datetime.combine(d, time(8, 30) if late else time(7, 50)).replace(tzinfo=tz)
                AttendanceRecord.objects.create(organisation=self.org, user=u, date=d, check_in=when,
                                                status="late" if late else "present", source="qr")

    def test_admin_numbers(self):
        ctx = admin_dashboard(self.org, self.admin)
        self.assertEqual((ctx["total"], ctx["present"], ctx["late"], ctx["on_time"]), (5, 3, 1, 2))
        self.assertEqual(ctx["not_in"], 2)
        self.assertEqual(len(ctx["tabs"]["in"]), 3)
        self.assertEqual({p["user"].username for p in ctx["tabs"]["out"]}, {"DSH-0001", "DSH-0005"})
        self.assertEqual(len(ctx["trend"]), 14)
        self.assertEqual(sum(d["pct"] for d in ctx["donut"][:2]), 60)
        self.assertEqual(ctx["arrivals"]["count"], 18)
        self.assertEqual(ctx["arrivals"]["on_time_pct"], 67)
        self.assertEqual(ctx["punctuality"]["late"][0]["person"], self.staff[2])
        self.assertIsNone(ctx["setup"])                     # location, people and attendance all there

    def test_setup_checklist_for_a_new_organisation(self):
        org = Organisation.objects.create(code="NEW", name="New Org")
        admin = User.objects.create_user(username="NEW-0001", password="x", organisation=org, role=User.ROLE_ADMIN)
        ctx = admin_dashboard(org, admin)
        self.assertEqual(ctx["setup"]["done"], 0)
        self.assertIsNone(ctx["arrivals"])
        self.assertIsNone(ctx["punctuality"])

    def test_staff_week_and_streak(self):
        rec = AttendanceRecord.objects.get(user=self.staff[0], date=timezone.localdate())
        ctx = staff_home(self.staff[0], rec)
        self.assertEqual(ctx["streak"], 6)
        self.assertEqual(len(ctx["week"]), 7)
        self.assertEqual(sum(1 for d in ctx["week"] if d["today"]), 1)
        self.assertEqual(ctx["avg_arrival"], "7:50 AM")

    def test_pages_render(self):
        self.client.login(username="DSH-0001", password="pw-123456")
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "Who's in today")
        self.assertContains(r, "Arrival times")
        self.assertContains(r, "Person4")
        r = self.client.get(reverse("portal"))
        self.assertContains(r, "This week")

    def test_platform_overview_renders(self):
        User.objects.create_superuser(username="root", password="pw-123456", email="r@x.test")
        self.client.login(username="root", password="pw-123456")
        r = self.client.get(reverse("platform"))
        self.assertContains(r, "Revenue, last 6 months")
        self.assertContains(r, "Dash Org")
