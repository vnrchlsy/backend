from django.urls import path

from community.views import (NeedPledgesView, NeedReceivedView, PledgeCancelView,
                             ShelterNeedsView)

urlpatterns = [
    path("shelters/<uuid:account_id>/needs", ShelterNeedsView.as_view()),
    path("needs/<uuid:need_id>/pledges", NeedPledgesView.as_view()),
    path("needs/<uuid:need_id>/received", NeedReceivedView.as_view()),
    path("pledges/<uuid:pledge_id>/cancel", PledgeCancelView.as_view()),
]
