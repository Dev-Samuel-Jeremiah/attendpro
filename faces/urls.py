from django.urls import path

from . import views

urlpatterns = [
    path("manage/faces/", views.faces, name="faces"),
    path("manage/faces/<int:pk>/review/", views.face_review, name="face_review"),
    path("manage/faces/member/<int:user_pk>/", views.face_enrol, name="face_enrol"),
    path("manage/faces/photo/<str:kind>/<int:pk>/", views.face_photo, name="face_photo"),
]
