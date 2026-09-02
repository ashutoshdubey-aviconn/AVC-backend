from django.urls import path

from .views import RecoveryUploadAPIView, RecoveryHealthAPIView, RecoveryMetricsAPIView

urlpatterns = [
    path("upload/", RecoveryUploadAPIView.as_view(), name="recovery-upload"),
    path("status/", RecoveryHealthAPIView.as_view(), name="recovery-status"),
    path("metrics/", RecoveryMetricsAPIView.as_view(), name="recovery-metrics"),
]
