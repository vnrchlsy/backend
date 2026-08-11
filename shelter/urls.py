from django.urls import path

from shelter.views import ShelterDashboardView, ShelterProfileView

urlpatterns = [
    path("shelter/profile", ShelterProfileView.as_view()),
    path("shelter/dashboard", ShelterDashboardView.as_view()),
]
