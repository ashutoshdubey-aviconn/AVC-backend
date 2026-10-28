from django.urls import path

from .views import RecoveryUploadAPIView

urlpatterns = [
    path("upload/", RecoveryUploadAPIView.as_view(), name="recovery-upload"),
]
