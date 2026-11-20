from django.urls import path

from . import views

urlpatterns = [
    path("me/leave/", views.my_leave, name="my_leave"),
    path("me/leave/<int:pk>/cancel/", views.my_leave_cancel, name="my_leave_cancel"),
    path("manage/leave/", views.leave_admin, name="leave_admin"),
    path("manage/leave/<int:pk>/decide/", views.leave_decide, name="leave_decide"),
    path("manage/leave/types/add/", views.leave_type_edit, name="leave_type_add"),
    path("manage/leave/types/<int:pk>/", views.leave_type_edit, name="leave_type_edit"),
]
