from django.urls import path

from volunteer.views import (ShelterShiftCancelView, ShelterShiftDetailView, ShelterShiftsView)

urlpatterns = [
    path("shelter/shifts", ShelterShiftsView.as_view()),
    path("shelter/shifts/<uuid:shift_id>", ShelterShiftDetailView.as_view()),
    path("shelter/shifts/<uuid:shift_id>/cancel", ShelterShiftCancelView.as_view()),
]
