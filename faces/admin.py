from django.contrib import admin

from .models import FaceCheck, FaceProfile


@admin.register(FaceProfile)
class FaceProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "organisation", "source", "reviewed", "updated_at")
    exclude = ("embeddings",)


@admin.register(FaceCheck)
class FaceCheckAdmin(admin.ModelAdmin):
    list_display = ("user", "organisation", "result", "score", "created_at")
    list_filter = ("result",)
