import json
from datetime import datetime, time, timedelta
from unittest import mock

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Plan
from core import analytics, services
from core.models import AttendanceRecord, Branch, Organisation, ScanLog, User

HQ = (9.896500, 8.858300)        # main location
NORTH = (9.950000, 8.880000)     # ~6.4 km away


def near(p, metres_north=30):
    return {"lat": p[0] + metres_north / 111_195, "lng": p[1], "accuracy": 10}


def at(hour, minute=0, day=None):
    return timezone.make_aware(datetime.combine(day or timezone.localdate(), time(hour, minute)))


class Base(TestCase):
    plan = "enterprise"

    def setUp(self):
        self.org = Organisation.objects.create(code="BR", name="Branchy", plan=Plan.objects.get(slug=self.plan),
                                               latitude=HQ[0], longitude=HQ[1], location_radius_m=100,
                                               work_start=time(8), work_end=time(23, 59))
        self.north = Branch.objects.create(organisation=self.org, name="North", latitude=NORTH[0],
                                           longitude=NORTH[1], radius_m=150)
        self.admin = User.objects.create_user(username="BR-0001", password="x", organisation=self.org,
                                              role=User.ROLE_ADMIN)
        self.hq_member = User.objects.create_user(username="BR-0002", password="x", organisation=self.org)
        self.north_member = User.objects.create_user(username="BR-0003", password="x", organisation=self.org,
                                                     branch=self.north)
        self.rf = RequestFactory().post("/")

    def set_plan(self, slug):
        self.org.plan = Plan.objects.get(slug=slug)
        self.org.save()
        self.org.forget_plan()
        for u in (self.hq_member, self.north_member, self.admin):
            u.organisation = self.org

    def clock(self, user, loc):
        with mock.patch("django.utils.timezone.now", return_value=at(9)):
            return services.clock_by_location(user, self.rf, loc["lat"], loc["lng"], loc["accuracy"])


class TokenTests(Base):
    def test_branch_token_round_trip(self):
        token, _ = services.make_token(self.org, self.north)
        self.assertEqual(services.parse_token(token), (self.org, self.north))
        self.assertEqual(services.parse_token(services.make_token(self.org)[0]), (self.org, None))

    def test_branch_id_cannot_be_swapped(self):
        token, _ = services.make_token(self.org, self.north)
        other = Branch.objects.create(organisation=self.org, name="South")
        forged = token.replace(f"-{self.north.id}.", f"-{other.id}.")
        self.assertEqual(services.parse_token(forged), (None, None))

    def test_inactive_branch_token_rejected(self):
        token, _ = services.make_token(self.org, self.north)
        self.north.is_active = False
        self.north.save()
        self.assertEqual(services.parse_token(token), (None, None))


class ClockSiteTests(Base):
    def test_geofencing_lets_staff_clock_in_at_any_branch(self):
        r = self.clock(self.hq_member, near(NORTH))
        self.assertEqual(r.action, "check_in")
        rec = AttendanceRecord.objects.get(user=self.hq_member)
        self.assertEqual(rec.branch, self.north)
        self.assertEqual(ScanLog.objects.get(user=self.hq_member).branch, self.north)

    def test_without_geofencing_only_own_branch(self):
        ent = Plan.objects.get(slug="enterprise")
        ent.features.remove(*ent.features.filter(code="geofencing"))
        self.set_plan("enterprise")
        self.assertFalse(self.clock(self.north_member, near(HQ)).ok)
        self.assertEqual(self.clock(self.north_member, near(NORTH)).action, "check_in")
        self.assertFalse(self.clock(self.hq_member, near(NORTH)).ok)
        self.assertEqual(self.clock(self.hq_member, near(HQ)).action, "check_in")

    def test_professional_ignores_branches(self):
        self.set_plan("professional")
        self.assertEqual(self.clock(self.north_member, near(HQ)).action, "check_in")  # main location only
        self.assertIsNone(AttendanceRecord.objects.get(user=self.north_member).branch)

    def test_branch_without_location_explains(self):
        ent = Plan.objects.get(slug="enterprise")
        ent.features.remove(*ent.features.filter(code="geofencing"))
        self.north.latitude = self.north.longitude = None
        self.north.save()
        self.set_plan("enterprise")
        self.assertEqual(self.clock(self.north_member, near(NORTH)).title, "Location not set up")


class GeofencedQrTests(Base):
    def scan(self, token, loc=None):
        with mock.patch("django.utils.timezone.now", return_value=at(9)):
            return services.mark_attendance(self.hq_member, token, self.rf, location=loc)

    def test_qr_needs_location_inside_the_scanned_site(self):
        token, _ = services.make_token(self.org, self.north)
        self.assertEqual(self.scan(token).title, "Location needed")
        far = self.scan(token, near(HQ))
        self.assertFalse(far.ok)
        self.assertIn("from North", far.message)
        ok = self.scan(token, near(NORTH))
        self.assertEqual(ok.action, "check_in")
        self.assertEqual(AttendanceRecord.objects.get(user=self.hq_member).branch, self.north)

    def test_professional_qr_needs_no_location(self):
        self.set_plan("professional")
        self.assertEqual(self.scan(services.make_token(self.org)[0]).action, "check_in")

    def test_api_scan_with_pending_scan_and_location(self):
        self.client.force_login(self.hq_member)
        session = self.client.session
        session["pending_scan"] = {"org": self.org.id, "branch": self.north.id, "at": timezone.now().timestamp()}
        session.save()
        resp = self.client.post(reverse("api_scan"), json.dumps(dict(pending=True, **near(NORTH))),
                                content_type="application/json")
        self.assertTrue(resp.json()["ok"], resp.json())

    def test_phone_camera_link_shows_location_page(self):
        self.client.force_login(self.hq_member)
        resp = self.client.get(reverse("scan") + "?t=" + services.make_token(self.org)[0])
        self.assertContains(resp, "Confirming your location")
        self.assertFalse(AttendanceRecord.objects.exists())


class BranchPageTests(Base):
    def test_branch_kiosk(self):
        resp = self.client.get(reverse("kiosk", args=[self.north.kiosk_key]))
        self.assertContains(resp, "North")
        data = self.client.get(reverse("kiosk_token", args=[self.north.kiosk_key])).json()
        self.assertEqual(data["total"], 1)
        self.set_plan("professional")
        self.assertEqual(self.client.get(reverse("kiosk", args=[self.north.kiosk_key])).status_code, 404)

    def test_admin_manages_branches(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("branches")), "North")
        self.client.post(reverse("branch_add"), {"name": "East", "address": "", "latitude": "9.9", "longitude": "8.9",
                                                 "radius_m": 120, "is_active": "on"})
        self.assertTrue(self.org.branches.filter(name="East", radius_m=120).exists())
        self.assertContains(self.client.get(reverse("members") + f"?branch={self.north.pk}"), "BR-0003")
        self.assertNotContains(self.client.get(reverse("members") + f"?branch={self.north.pk}"), "BR-0002")
        for name in ("dashboard", "attendance", "reports", "member_add", "branch_add"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_branches_locked_on_professional(self):
        self.set_plan("professional")
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("branches")), reverse("billing"))
        self.assertRedirects(self.client.get(reverse("analytics")), reverse("billing"))


class AnalyticsTests(Base):
    def test_figures(self):
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday() + 7)  # last week's Monday
        for u in (self.admin, self.hq_member, self.north_member):
            u.date_joined = at(9, day=monday - timedelta(days=30))
            u.save()
        # Monday: on time, late, absent; Tuesday: all on time
        AttendanceRecord.objects.create(organisation=self.org, user=self.admin, date=monday, status="present",
                                        check_in=at(7, 55, monday), check_out=at(16, 0, monday))
        AttendanceRecord.objects.create(organisation=self.org, user=self.hq_member, date=monday, status="late",
                                        check_in=at(8, 40, monday))
        tue = monday + timedelta(days=1)
        for u in (self.admin, self.hq_member, self.north_member):
            AttendanceRecord.objects.create(organisation=self.org, user=u, date=tue, status="present",
                                            check_in=at(8, 0, tue))
        a = analytics.summarise(self.org, monday, tue, self.org.members.all())
        self.assertEqual(a["kpis"]["rate"], round(5 * 100 / 6, 1))
        self.assertEqual(a["kpis"]["punctuality"], 80.0)
        mon_row = next(w for w in a["weekdays"] if w["label"] == "Mon")
        self.assertEqual((mon_row["on_time"], mon_row["late"], mon_row["absent"]), (33.3, 33.3, 33.3))
        self.assertEqual(sum(b["n"] for b in a["histogram"]["buckets"]), 5)
        self.assertTrue(next(b for b in a["histogram"]["buckets"] if b["from"] == 8 * 60 + 30)["late"])
        self.assertEqual(a["people"]["most_absent"][0]["user"], self.north_member)
        self.assertEqual({g["name"] for g in a["branches"]}, {"Main location", "North"})

    def test_page_renders_with_filters(self):
        self.client.force_login(self.admin)
        for q in ("", "?range=7", "?range=90", "?range=last_month", f"?branch={self.north.pk}", "?start=2026-01-01&end=2026-02-01"):
            resp = self.client.get(reverse("analytics") + q)
            self.assertEqual(resp.status_code, 200, q)
            self.assertContains(resp, 'id="chart-data"')
