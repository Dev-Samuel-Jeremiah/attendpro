import hashlib
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from faces.engine import MODELS


class Command(BaseCommand):
    help = "Download the two OpenCV face models (about 39 MB) into FACE_MODEL_DIR, checking their SHA-256."

    def handle(self, *args, **opts):
        base = settings.FACE_MODEL_DIR
        base.mkdir(parents=True, exist_ok=True)
        for name, (url, sha) in MODELS.items():
            path = base / name
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
                self.stdout.write(f"{name}: already there")
                continue
            self.stdout.write(f"{name}: downloading…")
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
            if hashlib.sha256(data).hexdigest() != sha:
                raise CommandError(f"{name}: checksum mismatch, not saved")
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path)
            self.stdout.write(self.style.SUCCESS(f"{name}: saved"))
