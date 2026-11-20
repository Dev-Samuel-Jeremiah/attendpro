import random
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import AttendanceRecord, Department, Organisation, User

FIRST = ["Amina", "David", "Grace", "Ibrahim", "Joy", "Samuel", "Blessing", "Musa", "Esther", "Daniel",
         "Hauwa", "Peter", "Ruth", "Yakubu", "Mercy", "John", "Fatima", "Emmanuel", "Naomi", "Bitrus"]
LAST = ["Yusuf", "Gyang", "Okafor", "Bello", "Danjuma", "Pam", "Adeyemi", "Dung", "Ibrahim", "Choji"]


class Command(BaseCommand):
    help = "Create a demo organisation with members and 30 days of attendance."

    def handle(self, *args, **opts):
        org, created = Organisation.objects.get_or_create(
            code="DEMO", defaults={"name": "Demo Academy", "org_type": "school", "address": "Rayfield, Jos"})
        if not created:
            self.stdout.write(self.style.WARNING("Demo organisation already exists."))
            return

        admin = User.objects.create_user(username="DEMO-0001", password="admin123", first_name="Demo",
                                         last_name="Admin", organisation=org, role=User.ROLE_ADMIN,
                                         designation="Administrator")
        admin.date_joined = timezone.now() - timedelta(days=40)
        admin.save()
        depts = [Department.objects.create(organisation=org, name=n)
                 for n in ["Administration", "Teaching", "Accounts", "ICT"]]
        members = []
        for i in range(18):
            u = User.objects.create_user(
                username=org.next_member_id(), password="staff123",
                first_name=FIRST[i % len(FIRST)], last_name=random.choice(LAST), organisation=org,
                department=random.choice(depts), designation=random.choice(["Teacher", "Officer", "Accountant", "Technician"]))
            u.date_joined = timezone.now() - timedelta(days=40)
            u.save()
            members.append(u)

        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        for back in range(30, -1, -1):
            d = today - timedelta(days=back)
            if not org.is_working_day(d):
                continue
            for u in members + [admin]:
                roll = random.random()
                if roll < 0.08:
                    continue  # absent
                if roll < 0.11:
                    AttendanceRecord.objects.create(organisation=org, user=u, date=d, status="leave",
                                                    source="manual", note="Approved leave")
                    continue
                late = roll > 0.85
                arrive = datetime.combine(d, time(7, 30)) + timedelta(minutes=random.randint(0, 35) + (30 if late else 0))
                leave = datetime.combine(d, time(15, 50)) + timedelta(minutes=random.randint(0, 70))
                ci = timezone.make_aware(arrive, tz)
                co = timezone.make_aware(leave, tz) if back > 0 else None
                if back == 0 and ci > timezone.now():
                    continue
                status = "late" if arrive.time() > org.late_cutoff(d) else "present"
                AttendanceRecord.objects.create(organisation=org, user=u, date=d, check_in=ci, check_out=co,
                                                status=status)
        self.stdout.write(self.style.SUCCESS(
            "Demo ready.\n  Admin login:  DEMO-0001 / admin123\n  Staff login:  DEMO-0002 / staff123"))
