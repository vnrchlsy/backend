from django.urls import path

from verifications.views import PresignView, VerificationCreateView

urlpatterns = [
    path("media/presign", PresignView.as_view()),
    path("verifications", VerificationCreateView.as_view()),
]
