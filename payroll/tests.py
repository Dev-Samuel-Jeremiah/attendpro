from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Plan
from core.models import AttendanceRecord, Organisation, User
from leave import services as leave
from payroll import services
from payroll.models import PayProfile, PayrollLine, PaySettings


def at(day, h, m=0):
    return timezone.make_aware(datetime.combine(day, time(h, m)))


class PayrollTests(TestCase):
    """A Mon–Fri organisation, paid for October 2026 (22 working days)."""
    MONTH = date(2026, 10, 1)

    def setUp(self):
        self.org = Organisation.objects.create(code="PY", name="Pay Org", plan=Plan.objects.get(slug="enterprise"),
                                               work_start=time(8), work_end=time(16))
        self.admin = User.objects.create_user(username="PY-0001", password="x", organisation=self.org,
                                              role=User.ROLE_ADMIN, first_name="Boss")
        self.staff = User.objects.create_user(username="PY-0002", password="x", organisation=self.org, first_name="Ada")
        for u in (self.admin, self.staff):
            u.date_joined = at(date(2026, 1, 5), 9)
            u.save()
        self.days = [date(2026, 10, d) for d in range(1, 32) if date(2026, 10, d).weekday() < 5]
        self.assertEqual(len(self.days), 22)

    def attend(self, user, days, late=()):
        for d in days:
            AttendanceRecord.objects.create(organisation=self.org, user=user, date=d, check_in=at(d, 9 if d in late else 8),
                                            check_out=at(d, 16), status="late" if d in late else "present")

    def line(self, user):
        run = services.prepare(self.org, self.MONTH, self.admin)
        return run, run.lines.get(user=user)

    def test_monthly_salary_with_late_and_absent_deductions(self):
        PayProfile.objects.create(user=self.staff, pay_type="monthly", rate=Decimal("220000"))
        PaySettings.objects.create(organisation=self.org, late_fee=500, free_lates=1)
        self.attend(self.staff, self.days[:20], late=self.days[:3])      # 2 absent, 3 late
        _, l = self.line(self.staff)
        self.assertEqual((l.attended, l.absent, l.late), (20, 2, 3))
        self.assertEqual(l.gross, Decimal("220000.00"))
        self.assertEqual(l.absence_deduction, Decimal("20000.00"))         # 2 × 10,000 a day
        self.assertEqual(l.late_deduction, Decimal("1000.00"))             # (3 − 1 free) × 500
        self.assertEqual(l.net, Decimal("199000.00"))

    def test_unpaid_leave_counts_as_absence_paid_leave_does_not(self):
        PayProfile.objects.create(user=self.staff, pay_type="monthly", rate=Decimal("220000"))
        leave.ensure_types(self.org)
        self.attend(self.staff, self.days[2:])
        for name, d in (("Unpaid leave", self.days[0]), ("Annual leave", self.days[1])):
            req = leave.LeaveRequest.objects.create(organisation=self.org, user=self.staff, leave_type=self.org.leave_types.get(name=name),
                                                    start_date=d, end_date=d, days=1)
            leave.approve(req, self.admin)
        _, l = self.line(self.staff)
        self.assertEqual((l.unpaid_leave, l.paid_leave, l.absent), (1, 1, 0))
        self.assertEqual(l.absence_deduction, Decimal("10000.00"))

    def test_daily_and_hourly(self):
        PayProfile.objects.create(user=self.staff, pay_type="daily", rate=Decimal("5000"))
        PayProfile.objects.create(user=self.admin, pay_type="hourly", rate=Decimal("1000"))
        self.attend(self.staff, self.days[:10])
        self.attend(self.admin, self.days[:2])                            # 2 × 8 h
        run = services.prepare(self.org, self.MONTH, self.admin)
        self.assertEqual(run.lines.get(user=self.staff).gross, Decimal("50000.00"))
        self.assertEqual(run.lines.get(user=self.admin).gross, Decimal("16000.00"))

    def test_adjustment_finalise_and_payslips(self):
        PayProfile.objects.create(user=self.staff, pay_type="monthly", rate=Decimal("100000"),
                                  account_number="0123456789", bank_name="GTBank")
        self.attend(self.staff, self.days)
        run, l = self.line(self.staff)
        self.client.force_login(self.admin)
        self.client.post(reverse("payroll_run", args=[run.pk]), {f"adj{l.id}": "5000", f"note{l.id}": "Bonus",
                                                                 "action": "save"})
        l.refresh_from_db()
        self.assertEqual(l.net, Decimal("105000.00"))
        services.prepare(self.org, self.MONTH, self.admin)                 # recalculating keeps the bonus
        l.refresh_from_db()
        self.assertEqual((l.adjustment, l.net), (Decimal("5000.00"), Decimal("105000.00")))
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(reverse("my_payslips")), "October 2026")
        self.assertEqual(self.client.get(reverse("my_payslip", args=[l.pk])).status_code, 404)
        self.client.force_login(self.admin)
        self.client.post(reverse("payroll_run", args=[run.pk]), {f"adj{l.id}": "5000", "action": "finalise"})
        run.refresh_from_db()
        self.assertTrue(run.is_final)
        with self.assertRaises(ValueError):
            services.prepare(self.org, self.MONTH, self.admin)
        bank = self.client.get(reverse("payroll_run", args=[run.pk]) + "?export=bank").content.decode("utf-8-sig")
        self.assertIn("0123456789", bank)
        self.assertIn("105000.00", bank)
        self.assertTrue(self.client.get(reverse("payroll_run", args=[run.pk]) + "?export=xlsx").content.startswith(b"PK"))
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("my_payslips")), "October 2026")
        self.assertTrue(self.client.get(reverse("my_payslip", args=[l.pk])).content.startswith(b"%PDF"))
        self.assertTrue(self.staff.notifications.filter(kind="pay").exists())

    def test_pages_and_gating(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("payroll"), {"month": "2026-10"})
        run = self.org.payroll_runs.get()
        self.assertRedirects(resp, reverse("payroll_run", args=[run.pk]))
        for name in ("payroll", "pay_rates", "pay_rules"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.client.post(reverse("pay_rates"), {f"t{self.staff.id}": "daily", f"r{self.staff.id}": "7,500",
                                                f"a{self.staff.id}": "01-2345"})
        p = PayProfile.objects.get(user=self.staff)
        self.assertEqual((p.pay_type, p.rate, p.account_number), ("daily", Decimal("7500"), "012345"))
        self.org.plan = Plan.objects.get(slug="professional")
        self.org.save()
        self.assertRedirects(self.client.get(reverse("payroll")), reverse("billing"))

    def test_joined_mid_month_is_pro_rated(self):
        PayProfile.objects.create(user=self.staff, pay_type="monthly", rate=Decimal("220000"))
        self.staff.date_joined = at(date(2026, 10, 19), 9)                # Monday: 10 working days left
        self.staff.save()
        self.attend(self.staff, [d for d in self.days if d >= date(2026, 10, 19)])
        _, l = self.line(self.staff)
        self.assertEqual((l.gross, l.net), (Decimal("100000.00"), Decimal("100000.00")))
        self.assertEqual(PayrollLine.objects.count(), 2)
