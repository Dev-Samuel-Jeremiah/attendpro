import io
import tempfile
import zipfile
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import Plan
from core.models import AttendanceRecord, Branch, Department, Organisation, User
from recovery import services
from recovery.models import DeletedItem, OrgBackup

PRIVATE = tempfile.mkdtemp()


@override_settings(PRIVATE_ROOT=PRIVATE)
class RecoveryTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(code="RC", name="Recover", plan=Plan.objects.get(slug="enterprise"))
        self.admin = User.objects.create_user(username="RC-0001", password="x", organisation=self.org,
                                              role=User.ROLE_ADMIN, first_name="Boss")
        self.dept = Department.objects.create(organisation=self.org, name="Accounts")
        self.staff = User.objects.create_user(username="RC-0002", password="x", organisation=self.org,
                                              first_name="Ada", department=self.dept)
        self.rec = AttendanceRecord.objects.create(organisation=self.org, user=self.staff, date=timezone.localdate(),
                                                   check_in=timezone.now(), status="present", note="hello")
        self.client.force_login(self.admin)

    def test_deleted_entry_can_be_restored_once(self):
        self.client.post(reverse("record_edit", args=[self.rec.pk]), {"delete": "1"})
        self.assertFalse(AttendanceRecord.objects.exists())
        item = DeletedItem.objects.get()
        self.assertContains(self.client.get(reverse("backups")), "Ada")
        self.client.post(reverse("restore_item", args=[item.pk]))
        rec = AttendanceRecord.objects.get()
        self.assertEqual((rec.user, rec.note, rec.status), (self.staff, "hello", "present"))
        with self.assertRaises(services.RestoreError):
            services.restore(DeletedItem.objects.get())

    def test_restore_refuses_to_overwrite(self):
        services.trash(self.rec, self.admin)
        AttendanceRecord.objects.create(organisation=self.org, user=self.staff, date=timezone.localdate(), status="leave")
        with self.assertRaisesMessage(services.RestoreError, "already has an entry"):
            services.restore(DeletedItem.objects.get())

    def test_department_and_branch_come_back_with_their_people(self):
        self.client.post(reverse("department_delete", args=[self.dept.pk]))
        self.staff.refresh_from_db()
        self.assertIsNone(self.staff.department)
        services.restore(DeletedItem.objects.get(kind="department"))
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.department.name, "Accounts")
        b = Branch.objects.create(organisation=self.org, name="North", radius_m=150)
        self.staff.branch = b
        self.staff.save()
        self.client.post(reverse("branch_edit", args=[b.pk]), {"delete": "1"})
        self.assertFalse(Branch.objects.exists())
        services.restore(DeletedItem.objects.get(kind="branch"))
        self.staff.refresh_from_db()
        self.assertEqual((self.staff.branch.name, self.staff.branch.radius_m), ("North", 150))

    def test_lower_plans_delete_for_good(self):
        self.org.plan = Plan.objects.get(slug="professional")
        self.org.save()
        self.org.forget_plan()
        self.rec.organisation = self.org
        services.trash(self.rec, self.admin)
        self.assertFalse(DeletedItem.objects.exists())
        self.assertRedirects(self.client.get(reverse("backups")), reverse("billing"))

    def test_export_and_backups(self):
        data = self.client.get(reverse("backup_export")).content
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        for n in ("members.csv", "attendance.csv", "leave.csv", "payroll.csv", "README.txt"):
            self.assertIn(n, names)
        self.assertIn(b"RC-0002", zipfile.ZipFile(io.BytesIO(data)).read("members.csv"))
        self.assertEqual(services.weekly_backups(), ["RC"])
        self.assertEqual(services.weekly_backups(), [])                    # not again within the week
        later = timezone.now() + timedelta(days=7, minutes=1)
        self.assertEqual(services.weekly_backups(later), ["RC"])
        b = OrgBackup.objects.first()
        resp = self.client.get(reverse("backup_download", args=[b.pk]))
        self.assertEqual(resp["Content-Type"], "application/zip")
        other = Organisation.objects.create(code="OT", name="Other", plan=Plan.objects.get(slug="enterprise"))
        self.client.force_login(User.objects.create_user(username="OT-0001", password="x", organisation=other,
                                                         role=User.ROLE_ADMIN))
        self.assertEqual(self.client.get(reverse("backup_download", args=[b.pk])).status_code, 404)

    def test_only_eight_weekly_backups_kept(self):
        for _ in range(10):
            services.make_backup(self.org)
        self.assertEqual(self.org.backups.count(), services.KEEP_AUTOMATIC)

    def test_deleted_items_expire(self):
        services.trash(self.rec, self.admin)
        with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(days=31)):
            services.purge_deleted()
        self.assertFalse(DeletedItem.objects.exists())

    def test_scheduled_job_runs(self):
        from django.core.management import call_command
        out = io.StringIO()
        call_command("send_alerts", stdout=out)
        self.assertIn("RC: weekly backup made", out.getvalue())
