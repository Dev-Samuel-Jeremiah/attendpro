import base64
import io
import json
import tempfile
from datetime import datetime, time
from unittest import mock

import numpy as np
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from billing.models import Plan
from core import services as core
from core.models import AttendanceRecord, Organisation, User
from faces import engine
from faces.models import FaceCheck, FaceProfile

PRIVATE = tempfile.mkdtemp()


def jpeg_data_url():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (180, 140, 120)).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def vec(seed):
    v = np.random.default_rng(seed).normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


@override_settings(PRIVATE_ROOT=PRIVATE)
class FaceTests(TestCase):
    HQ = (9.8965, 8.8583)

    def setUp(self):
        self.org = Organisation.objects.create(code="FC", name="Faces", plan=Plan.objects.get(slug="enterprise"),
                                               latitude=self.HQ[0], longitude=self.HQ[1],
                                               work_start=time(8), work_end=time(23, 59))
        self.admin = User.objects.create_user(username="FC-0001", password="x", organisation=self.org,
                                              role=User.ROLE_ADMIN)
        self.user = User.objects.create_user(username="FC-0002", password="x", organisation=self.org)
        self.rf = RequestFactory().post("/")
        self.at9 = timezone.make_aware(datetime.combine(timezone.localdate(), time(9)))

    def clock(self, selfie=None, faces=None, available=True):
        with mock.patch("django.utils.timezone.now", return_value=self.at9), \
             mock.patch.object(engine, "available", return_value=available), \
             mock.patch.object(engine, "embeddings", return_value=faces or [vec(1), vec(1)]):
            return core.clock_by_location(self.user, self.rf, self.HQ[0], self.HQ[1], 10, selfie=selfie)

    def test_asks_for_selfie_then_registers_first_face(self):
        self.assertEqual(self.clock().action, "need_selfie")
        self.assertFalse(AttendanceRecord.objects.exists())
        r = self.clock(jpeg_data_url())
        self.assertEqual(r.action, "check_in")
        profile = FaceProfile.objects.get(user=self.user)
        self.assertEqual((profile.source, profile.reviewed), ("auto", False))
        self.assertEqual(FaceCheck.objects.get().result, "enrolled")
        self.assertTrue(self.admin.notifications.filter(kind="face").exists())

    def test_match_and_mismatch(self):
        FaceProfile.objects.create(user=self.user, organisation=self.org,
                                   embeddings=engine.to_bytes(vec(1)) + engine.to_bytes(vec(1)))
        bad = self.clock(jpeg_data_url(), faces=[vec(2), vec(2)])
        self.assertEqual(bad.title, "Face doesn't match")
        self.assertFalse(AttendanceRecord.objects.exists())
        good = self.clock(jpeg_data_url(), faces=[vec(1) * .98 + vec(3) * .02])
        self.assertEqual(good.action, "check_in")
        self.assertEqual(list(FaceCheck.objects.values_list("result", flat=True).order_by("created_at")),
                         ["mismatch", "match"])

    def test_check_out_needs_no_selfie(self):
        AttendanceRecord.objects.create(organisation=self.org, user=self.user, date=timezone.localdate(),
                                        check_in=self.at9.replace(hour=8), status="present")
        with mock.patch("django.utils.timezone.now", return_value=self.at9.replace(hour=17)):
            r = core.clock_by_location(self.user, self.rf, self.HQ[0], self.HQ[1], 10)
        self.assertEqual(r.action, "check_out")

    def test_switched_off_or_lower_plan(self):
        self.org.face_required = False
        self.org.save()
        self.assertEqual(self.clock().action, "check_in")
        AttendanceRecord.objects.all().delete()
        self.org.face_required = True
        self.org.plan = Plan.objects.get(slug="professional")
        self.org.save()
        self.org.forget_plan()
        self.user.organisation = self.org
        self.assertEqual(self.clock().action, "check_in")

    def test_no_auto_registration(self):
        self.org.face_auto_enrol = False
        self.org.save()
        self.assertEqual(self.clock(jpeg_data_url()).title, "Your face isn't registered yet")

    def test_engine_missing_is_recorded_not_blocking(self):
        self.assertEqual(self.clock(jpeg_data_url(), available=False).action, "check_in")
        self.assertEqual(FaceCheck.objects.get().result, "unchecked")

    def test_bad_photo(self):
        self.assertEqual(self.clock("data:image/jpeg;base64,!!!").title, "Photo not received")

    def test_pending_scan_survives_the_selfie_step(self):
        self.client.force_login(self.user)
        s = self.client.session
        s["pending_scan"] = {"org": self.org.id, "branch": None, "at": timezone.now().timestamp()}
        s.save()
        here = {"lat": self.HQ[0], "lng": self.HQ[1], "accuracy": 10}
        resp = self.client.post(reverse("api_scan"), json.dumps(dict(pending=True, **here)),
                                content_type="application/json")
        self.assertEqual(resp.json()["action"], "need_selfie")
        self.assertIn("pending_scan", self.client.session)
        with mock.patch.object(engine, "available", return_value=True), \
             mock.patch.object(engine, "embeddings", return_value=[vec(1)]):
            resp = self.client.post(reverse("api_scan"), json.dumps(dict(pending=True, selfie=jpeg_data_url(), **here)),
                                    content_type="application/json")
        self.assertTrue(resp.json()["ok"], resp.json())
        self.assertNotIn("pending_scan", self.client.session)

    def test_admin_pages_and_private_photos(self):
        self.clock(jpeg_data_url())
        self.client.force_login(self.admin)
        page = self.client.get(reverse("faces"))
        self.assertContains(page, self.user.display_name)
        p = FaceProfile.objects.get()
        self.assertEqual(self.client.get(reverse("face_photo", args=["ref", p.pk]))["Content-Type"], "image/jpeg")
        self.assertEqual(self.client.get(reverse("faces") + "?tab=checks").status_code, 200)
        self.assertEqual(self.client.get(reverse("member_edit", args=[self.user.pk])).status_code, 200)
        self.client.post(reverse("face_review", args=[p.pk]), {"action": "approve"})
        p.refresh_from_db()
        self.assertTrue(p.reviewed)
        other = Organisation.objects.create(code="OT", name="Other", plan=Plan.objects.get(slug="enterprise"))
        stranger = User.objects.create_user(username="OT-0001", password="x", organisation=other, role=User.ROLE_ADMIN)
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("face_photo", args=["ref", p.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("face_photo", args=["check", FaceCheck.objects.get().pk])).status_code, 404)
