from django.urls import path

from moderation.views import ModerationFlagCreateView

urlpatterns = [
    path("moderation/flags", ModerationFlagCreateView.as_view()),
]
