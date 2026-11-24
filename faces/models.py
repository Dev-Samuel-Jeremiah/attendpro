from django.conf import settings
from django.db import models

from core.storage import private_storage


class FaceProfile(models.Model):
    """A member's reference face: the numbers the selfie is compared with, plus the photo they came from."""
    SOURCE_ADMIN, SOURCE_AUTO = "admin", "auto"
    SOURCE_CHOICES = [(SOURCE_ADMIN, "Registered by an administrator"), (SOURCE_AUTO, "First clock-in selfie")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="face")
    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="face_profiles")
    embeddings = models.BinaryField()  # one or more 128-number float32 descriptions, back to back
    photo = models.ImageField(storage=private_storage, upload_to="faces/reference/", blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_ADMIN)
    reviewed = models.BooleanField(default=False, help_text="An administrator has confirmed this is the right person")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Face of {self.user}"


class FaceCheck(models.Model):
    """Every selfie taken at check-in and what the comparison decided (kept 90 days)."""
    MATCH, MISMATCH, NO_FACE, ENROLLED, UNCHECKED = "match", "mismatch", "no_face", "enrolled", "unchecked"
    RESULT_CHOICES = [(MATCH, "Matched"), (MISMATCH, "Didn't match"), (NO_FACE, "No face found"),
                      (ENROLLED, "Registered as reference"), (UNCHECKED, "Not checked (engine off)")]

    organisation = models.ForeignKey("core.Organisation", on_delete=models.CASCADE, related_name="face_checks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="face_checks")
    result = models.CharField(max_length=10, choices=RESULT_CHOICES)
    score = models.FloatField(null=True, blank=True)
    photo = models.ImageField(storage=private_storage, upload_to="faces/checks/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def accepted(self):
        return self.result in (self.MATCH, self.ENROLLED, self.UNCHECKED)
