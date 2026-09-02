from django.urls import path

from listings.views import ListingsView

urlpatterns = [
    path("listings", ListingsView.as_view()),
]
