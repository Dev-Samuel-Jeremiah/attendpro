from datetime import date, datetime, time, timedelta
from unittest import mock

from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import Plan
from core import services as core_services
from core.models import AttendanceRecord, Organisation, User
from leave import services
from leave.models import LeaveRequest
from notifications.models import Notification
from notifications.services import run_scheduled_alerts


def next_monday():
    today = timezone.localdate()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


class Base(TestCase):
    plan = "professional"

    def setUp(self):
        self.org = Organisation.objects.create(code="LV", name="Leave Org", plan=Plan.objects.get(slug=self.plan),
                                               work_start=time(8), work_end=time(16))
        self.admin = User.objects.create_user(username="LV-0001", password="x", organisation=self.org,
                                              role=User.ROLE_ADMIN, first_name="Boss", email="boss@lv.test")
        self.member = User.objects.create_user(username="LV-0002", password="x", organisation=self.org,
                                               first_name="Ada", email="ada@lv.test")
        services.ensure_types(self.org)
        self.annual = self.org.leave_types.get(name="Annual leave")


class LeaveRuleTests(Base):
    def test_counts_working_days_only(self):
        mon = next_monday()
        req = services.submit(self.member, self.annual, mon, mon + timedelta(days=6))  # Mon–Sun
        self.assertEqual(req.days, 5)

    def test_cannot_exceed_allowance(self):
        mon = next_monday()
        self.annual.days_per_year = 3
        self.annual.save()
        with self.assertRaisesMessage(services.LeaveError, "3 annual leave days left"):
            services.submit(self.member, self.annual, mon, mon + timedelta(days=4))

    def test_no_overlap(self):
        mon = next_monday()
        services.submit(self.member, self.annual, mon, mon + timedelta(days=1))
        with self.assertRaisesMessage(services.LeaveError, "already have leave"):
            services.submit(self.member, self.org.leave_types.get(name="Sick leave"), mon + timedelta(days=1),
                            mon + timedelta(days=2))

    def test_weekend_only_rejected(self):
        sat = next_monday() + timedelta(days=5)
        with self.assertRaisesMessage(services.LeaveError, "non-working"):
            services.submit(self.member, self.annual, sat, sat + timedelta(days=1))

    def test_approve_marks_days_on_leave_and_cancel_restores(self):
        mon = next_monday()
        req = services.submit(self.member, self.annual, mon, mon + timedelta(days=2))
        services.approve(req, self.admin, "Enjoy")
        recs = AttendanceRecord.objects.filter(user=self.member)
        self.assertEqual(recs.count(), 3)
        self.assertTrue(all(r.status == "leave" and r.source == "leave" for r in recs))
        balance = {b["type"].name: b for b in services.balances(self.member, mon.year)}["Annual leave"]
        self.assertEqual((balance["used"], balance["left"]), (3, 17))
        services.cancel(req, self.admin)
        self.assertFalse(AttendanceRecord.objects.filter(user=self.member).exists())

    def test_approval_keeps_days_they_came_in(self):
        mon = next_monday()
        AttendanceRecord.objects.create(organisation=self.org, user=self.member, date=mon, status="present",
                                        check_in=timezone.make_aware(datetime.combine(mon, time(8))))
        req = services.submit(self.member, self.annual, mon, mon + timedelta(days=1))
        services.approve(req, self.admin)
        self.assertEqual(AttendanceRecord.objects.get(user=self.member, date=mon).status, "present")
        self.assertEqual(AttendanceRecord.objects.get(user=self.member, date=mon + timedelta(days=1)).status, "leave")

    def test_cannot_decide_twice(self):
        req = services.submit(self.member, self.annual, next_monday(), next_monday())
        services.reject(req, self.admin, "Busy week")
        with self.assertRaises(services.LeaveError):
            services.approve(req, self.admin)


class LeaveNotificationTests(Base):
    @override_settings(EMAIL_HOST="smtp.test", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_request_and_decision_notify_in_app_and_by_email(self):
        req = services.submit(self.member, self.annual, next_monday(), next_monday())
        self.assertTrue(Notification.objects.filter(user=self.admin, kind="leave").exists())
        services.approve(req, self.admin)
        self.assertTrue(Notification.objects.filter(user=self.member, title="Your leave was approved").exists())
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["ada@lv.test", "boss@lv.test"])

    def test_email_off_by_default_when_no_smtp(self):
        services.submit(self.member, self.annual, next_monday(), next_monday())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Notification.objects.count(), 1)


class LeaveViewTests(Base):
    def test_member_requests_admin_approves(self):
        self.client.force_login(self.member)
        mon = next_monday()
        resp = self.client.post(reverse("my_leave"), {"leave_type": self.annual.pk, "start_date": mon,
                                                      "end_date": mon + timedelta(days=1), "reason": "Wedding"})
        self.assertRedirects(resp, reverse("my_leave"))
        req = LeaveRequest.objects.get()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("leave_admin")), "Wedding")
        self.client.post(reverse("leave_decide", args=[req.pk]), {"action": "approve"})
        req.refresh_from_db()
        self.assertEqual(req.status, "approved")

    def test_member_cannot_decide(self):
        req = services.submit(self.member, self.annual, next_monday(), next_monday())
        self.client.force_login(self.member)
        self.client.post(reverse("leave_decide", args=[req.pk]), {"action": "approve"})
        req.refresh_from_db()
        self.assertEqual(req.status, "pending")

    def test_basic_plan_locked(self):
        self.org.plan = Plan.objects.get(slug="basic")
        self.org.save()
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("leave_admin")), reverse("billing"))
        self.assertRedirects(self.client.get(reverse("notifications")), reverse("billing"))

    def test_pages_render(self):
        services.submit(self.member, self.annual, next_monday(), next_monday())
        for user, names in ((self.admin, ["leave_admin", "my_leave", "notifications", "leave_type_add"]),
                            (self.member, ["my_leave", "notifications", "portal"])):
            self.client.force_login(user)
            for n in names:
                self.assertEqual(self.client.get(reverse(n)).status_code, 200, n)


class AlertTests(Base):
    def at(self, day, h, m=0):
        return timezone.make_aware(datetime.combine(day, time(h, m)))

    def test_absence_alert_once_after_cutoff(self):
        mon = next_monday()
        self.member.date_joined = self.at(mon - timedelta(days=10), 9)
        self.member.save()
        self.admin.date_joined = self.member.date_joined
        self.admin.save()
        AttendanceRecord.objects.create(organisation=self.org, user=self.admin, date=mon, status="present",
                                        check_in=self.at(mon, 8))
        self.assertEqual(run_scheduled_alerts(self.at(mon, 9)), [])           # before 08:10 + 1h
        self.assertIn(("LV", "absent", 1), run_scheduled_alerts(self.at(mon, 9, 15)))
        self.assertEqual(run_scheduled_alerts(self.at(mon, 9, 30)), [])        # only once a day
        self.assertTrue(Notification.objects.filter(user=self.member, kind="absent").exists())
        self.assertTrue(Notification.objects.filter(user=self.admin, title__startswith="1 person").exists())

    def test_people_on_leave_are_not_absent(self):
        mon = next_monday()
        for u in (self.member, self.admin):
            u.date_joined = self.at(mon - timedelta(days=10), 9)
            u.save()
        services.approve(services.submit(self.member, self.annual, mon, mon), self.admin)
        AttendanceRecord.objects.create(organisation=self.org, user=self.admin, date=mon, status="present",
                                        check_in=self.at(mon, 8))
        run_scheduled_alerts(self.at(mon, 10))
        self.assertFalse(Notification.objects.filter(kind="absent").exists())

    def test_checkout_reminder(self):
        mon = next_monday()
        AttendanceRecord.objects.create(organisation=self.org, user=self.member, date=mon, status="present",
                                        check_in=self.at(mon, 8))
        self.assertIn(("LV", "checkout", 1), run_scheduled_alerts(self.at(mon, 18, 5)))

    def test_plan_expiry_reminder(self):
        mon = next_monday()
        self.org.plan_expires_at = self.at(mon + timedelta(days=3), 12)
        self.org.save()
        self.assertIn(("LV", "plan_3", 1), run_scheduled_alerts(self.at(mon, 7)))

    def test_late_arrival_notifies_admin_in_app_only(self):
        req = RequestFactory().get("/")
        with mock.patch("django.utils.timezone.now", return_value=self.at(timezone.localdate(), 9)):
            core_services.record_attendance(self.member, self.org, req, source="qr")
        n = Notification.objects.get(user=self.admin)
        self.assertIn("arrived late", n.title)
        self.assertEqual(len(mail.outbox), 0)

    def test_basic_plan_gets_no_notifications(self):
        self.org.plan = Plan.objects.get(slug="basic")
        self.org.save()
        services.submit(self.member, self.annual, next_monday(), next_monday())
        self.assertFalse(Notification.objects.exists())


class PdfExportTests(Base):
    def test_report_pdf(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()
        AttendanceRecord.objects.create(organisation=self.org, user=self.member, date=today, status="late",
                                        check_in=timezone.now())
        resp = self.client.get(reverse("reports") + "?export=pdf")
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        resp = self.client.get(reverse("reports") + f"?start={date(today.year, 1, 1)}&end={today}&export=pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))  # long range: summary only
