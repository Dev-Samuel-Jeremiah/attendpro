"""Sign-in details for Google Play / App Store reviewers.

    python manage.py create_review_account            # create (or show again) the review organisation
    python manage.py create_review_account --reset    # new passwords

Creates "AttendPro Review" (code REVIEW) on the Enterprise plan with 12 people and 30 days of sample
attendance, so reviewers can see every screen. Its passwords are random and printed once; it is a
normal organisation, separate from real customers, and can be removed from Platform → Organisations.
"""
import random
import secrets
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import Plan
from core.models import AttendanceRecord, Department, Organisation, User

CODE = "REVIEW"
NAMES = [("Amina", "Yusuf"), ("David", "Gyang"), ("Grace", "Okafor"), ("Ibrahim", "Bello"), ("Joy", "Danjuma"),
         ("Samuel", "Pam"), ("Blessing", "Adeyemi"), ("Musa", "Dung"), ("Esther", "Ibrahim"), ("Daniel", "Choji"),
         ("Ruth", "Okafor")]


def _password():
    return "Rv-" + secrets.token_urlsafe(9)


class Command(BaseCommand):
    help = "Create sign-in details for app store reviewers (organisation code REVIEW)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Give both review accounts new passwords.")

    def handle(self, *args, reset=False, **opts):
        org = Organisation.objects.filter(code=CODE).first()
        if org:
            admin, staff = User.objects.get(username=f"{CODE}-0001"), User.objects.get(username=f"{CODE}-0002")
            if not reset:
                self.stdout.write(self.style.WARNING(
                    "The review organisation already exists. Run with --reset to set new passwords."))
                return
        else:
            org, admin, staff = self._create()
        pw_admin, pw_staff = _password(), _password()
        admin.set_password(pw_admin)
        admin.save(update_fields=["password"])
        staff.set_password(pw_staff)
        staff.save(update_fields=["password"])
        self.stdout.write(self.style.SUCCESS(
            "Review accounts ready. Paste these into Play Console → App content → App access:\n"
            f"  Administrator:  {admin.username} / {pw_admin}\n"
            f"  Staff member:   {staff.username} / {pw_staff}"))

    def _create(self):
        org = Organisation.objects.create(
            code=CODE, name="AttendPro Review", org_type="company", address="Rayfield, Jos",
            plan=Plan.objects.filter(slug="enterprise").first(), latitude=9.8965, longitude=8.8583,
            location_radius_m=5000, attendance_method="both")
        admin = User.objects.create_user(username=f"{CODE}-0001", password=_password(), first_name="Review",
                                         last_name="Admin", organisation=org, role=User.ROLE_ADMIN,
                                         designation="Administrator")
        depts = [Department.objects.create(organisation=org, name=n) for n in ["Administration", "Operations", "Accounts"]]
        people = []
        for i, (first, last) in enumerate(NAMES):
            people.append(User.objects.create_user(
                username=org.next_member_id(), password=_password(), first_name=first, last_name=last,
                organisation=org, department=depts[i % len(depts)],
                designation=random.choice(["Officer", "Accountant", "Supervisor"])))
        staff = people[0]

        rnd = random.Random(7)
        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        for back in range(30, 0, -1):
            d = today - timedelta(days=back)
            if not org.is_working_day(d):
                continue
            for u in people + [admin]:
                roll = rnd.random()
                if roll < 0.07:
                    continue
                if roll < 0.1:
                    AttendanceRecord.objects.create(organisation=org, user=u, date=d, status="leave",
                                                    source="manual", note="Approved leave")
                    continue
                late = roll > 0.86
                arrive = datetime.combine(d, time(7, 30)) + timedelta(minutes=rnd.randint(0, 35) + (30 if late else 0))
                leave = datetime.combine(d, time(16, 0)) + timedelta(minutes=rnd.randint(0, 60))
                AttendanceRecord.objects.create(
                    organisation=org, user=u, date=d, check_in=timezone.make_aware(arrive, tz),
                    check_out=timezone.make_aware(leave, tz),
                    status="late" if arrive.time() > org.late_cutoff(d) else "present")
        return org, admin, staff
