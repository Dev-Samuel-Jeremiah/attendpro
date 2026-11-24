from django.conf import settings
from django.core.files.storage import FileSystemStorage


def private_storage():
    """Storage for files that must never be served publicly (settings.PRIVATE_ROOT)."""
    return FileSystemStorage(location=settings.PRIVATE_ROOT)
