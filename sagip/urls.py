from django.urls import path

from sagip.views import (CaseStatusView, MyReportsView, MyRescuesView, ReportClaimView,
                         ReportDetailView, RescueMapView, ReportsCreateView)

urlpatterns = [
    path("reports", ReportsCreateView.as_view()),
    path("reports/map", RescueMapView.as_view()),
    path("reports/<uuid:report_id>", ReportDetailView.as_view()),
    path("reports/<uuid:report_id>/claim", ReportClaimView.as_view()),
    path("cases/<uuid:case_id>/status", CaseStatusView.as_view()),
    path("me/reports", MyReportsView.as_view()),
    path("me/rescues", MyRescuesView.as_view()),
]
