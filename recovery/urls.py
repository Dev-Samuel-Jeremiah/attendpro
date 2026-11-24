from django.urls import path

from . import views

urlpatterns = [
    path("manage/backups/", views.backups, name="backups"),
    path("manage/backups/new/", views.backup_now, name="backup_now"),
    path("manage/backups/export/", views.export_now, name="backup_export"),
    path("manage/backups/<int:pk>/download/", views.backup_download, name="backup_download"),
    path("manage/backups/deleted/<int:pk>/restore/", views.restore_item, name="restore_item"),
]
