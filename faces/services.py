"""Selfie checks at check-in. The heavy lifting is in engine.py (OpenCV, on this server)."""
import base64
import binascii
import io
import logging
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.urls import reverse

from billing import catalog

from . import engine
from .models import FaceCheck, FaceProfile

log = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 6 * 1024 * 1024
THUMB_SIDE = 360


class SelfieError(ValueError):
    pass


def required(org):
    """Does this organisation check faces at check-in?"""
    return org.has_feature(catalog.FACE) and org.face_required


def decode(data_url: str) -> bytes:
    """A `data:image/jpeg;base64,...` string from the browser camera → image bytes."""
    if not data_url or not isinstance(data_url, str):
        raise SelfieError("No photo was received. Take the selfie again.")
    payload = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise SelfieError("That photo couldn't be read. Take the selfie again.") from None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise SelfieError("That photo is too large. Take the selfie again.")
    return raw


def thumbnail(image_bytes: bytes) -> bytes:
    """A small JPEG kept for review (the full photo is never stored)."""
    from PIL import Image, ImageOps
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    except Exception:
        raise SelfieError("That photo couldn't be read. Take the selfie again.") from None
    img.thumbnail((THUMB_SIDE, THUMB_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82)
    return out.getvalue()


def _vectors_bytes(vectors):
    return b"".join(engine.to_bytes(v) for v in vectors)


def _references(profile):
    flat = engine.from_bytes(profile.embeddings)
    return [flat[i:i + 128] for i in range(0, len(flat) - 127, 128)]


@dataclass
class FaceOutcome:
    ok: bool
    title: str = ""
    message: str = ""
    check: FaceCheck | None = None


def _record(org, user, result, thumb, score=None):
    check = FaceCheck(organisation=org, user=user, result=result, score=score)
    if thumb:
        check.photo.save(f"{user.username}.jpg", ContentFile(thumb), save=False)
    check.save()
    return check


def verify(user, org, image_bytes: bytes) -> FaceOutcome:
    """Compare a check-in selfie with the member's reference face (registering it the first time)."""
    thumb = thumbnail(image_bytes)
    if not engine.available():
        log.warning("Face check skipped for %s: face models are not installed on this server", user.username)
        return FaceOutcome(True, check=_record(org, user, FaceCheck.UNCHECKED, thumb))
    try:
        vectors = engine.embeddings(image_bytes)
    except engine.FaceError as e:
        return FaceOutcome(False, "Face not found", str(e), _record(org, user, FaceCheck.NO_FACE, thumb))

    profile = FaceProfile.objects.filter(user=user).first()
    if profile is None:
        if not org.face_auto_enrol:
            return FaceOutcome(False, "Your face isn't registered yet",
                               "Ask your administrator to register your face, then try again.",
                               _record(org, user, FaceCheck.NO_FACE, thumb))
        profile = FaceProfile(user=user, organisation=org, embeddings=_vectors_bytes(vectors),
                              source=FaceProfile.SOURCE_AUTO)
        profile.photo.save(f"{user.username}.jpg", ContentFile(thumb), save=False)
        profile.save()
        from notifications.services import admins_of, notify
        notify(org, admins_of(org), f"New face registered for {user.display_name}",
               "Their first clock-in selfie is now their reference. Please check it's really them.",
               url=reverse("faces") + "?tab=review", kind="face", email=False)
        return FaceOutcome(True, check=_record(org, user, FaceCheck.ENROLLED, thumb, 1.0))

    score = engine.best_match(vectors, _references(profile))
    if score >= engine.MATCH_AT:
        return FaceOutcome(True, check=_record(org, user, FaceCheck.MATCH, thumb, round(score, 3)))
    return FaceOutcome(False, "Face doesn't match",
                       "This selfie doesn't match the face registered for your account. Try again facing a "
                       "light, without a mask or sunglasses. If it keeps failing, ask your administrator.",
                       _record(org, user, FaceCheck.MISMATCH, thumb, round(score, 3)))


def enrol(user, image_bytes: bytes, reviewed=True) -> FaceProfile:
    """Register (or replace) a member's reference face from a photo an administrator took or uploaded."""
    if not engine.available():
        raise SelfieError("Face matching isn't installed on this server yet.")
    try:
        vectors = engine.embeddings(image_bytes)
    except engine.FaceError as e:
        raise SelfieError(str(e)) from None
    thumb = thumbnail(image_bytes)
    profile = FaceProfile.objects.filter(user=user).first() or FaceProfile(user=user, organisation=user.organisation)
    if profile.photo:
        profile.photo.delete(save=False)
    profile.embeddings = _vectors_bytes(vectors)
    profile.source, profile.reviewed = FaceProfile.SOURCE_ADMIN, reviewed
    profile.photo.save(f"{user.username}.jpg", ContentFile(thumb), save=False)
    profile.save()
    return profile


def reset(user):
    profile = FaceProfile.objects.filter(user=user).first()
    if profile:
        if profile.photo:
            profile.photo.delete(save=False)
        profile.delete()


def purge_old_checks(before):
    for check in FaceCheck.objects.filter(created_at__lt=before).iterator():
        if check.photo:
            check.photo.delete(save=False)
        check.delete()
