from django.urls import path

from listings.views import ListingsView, ReportsMapView

urlpatterns = [
    path("listings", ListingsView.as_view()),
    path("reports/map", ReportsMapView.as_view()),
]
