from django.urls import path

from volunteer.views import (ShelterShiftCancelView, ShelterShiftDetailView, ShelterShiftsView,
                             ShiftDetailView, ShiftSignupView, ShiftsBrowseView,
                             SignupApproveView, SignupDeclineView)

urlpatterns = [
    path("shelter/shifts", ShelterShiftsView.as_view()),
    path("shelter/shifts/<uuid:shift_id>", ShelterShiftDetailView.as_view()),
    path("shelter/shifts/<uuid:shift_id>/cancel", ShelterShiftCancelView.as_view()),
    path("shelter/signups/<uuid:signup_id>/approve", SignupApproveView.as_view()),
    path("shelter/signups/<uuid:signup_id>/decline", SignupDeclineView.as_view()),
    path("shifts", ShiftsBrowseView.as_view()),
    path("shifts/<uuid:shift_id>", ShiftDetailView.as_view()),
    path("shifts/<uuid:shift_id>/signups", ShiftSignupView.as_view()),
]
