from django.urls import path

from sagip.views import (MyReportsView, ReportClaimView, ReportDetailView, RescueMapView,
                         ReportsCreateView)

urlpatterns = [
    path("reports", ReportsCreateView.as_view()),
    path("reports/map", RescueMapView.as_view()),
    path("reports/<uuid:report_id>", ReportDetailView.as_view()),
    path("reports/<uuid:report_id>/claim", ReportClaimView.as_view()),
    path("me/reports", MyReportsView.as_view()),
]
