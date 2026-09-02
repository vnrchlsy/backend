"""US-W1 · Abot-tulong wishlist endpoints (needs & pledges).

The `quantity_received` math and the `open -> fulfilled` flip are never done here — they go
through `community/needs.py::apply_received` under a row lock (D-S6-7).
"""
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.service import notify
from shelter.permissions import IsShelter

from .models import NeedPledge, NeedStatus, PledgeStatus, ShelterNeed
from .needs import NeedError, apply_received
from .serializers import NeedCreateSerializer, PledgeCreateSerializer, ReceivedSerializer

PAGE_SIZE = 20


def _err(code, message, status):
    return Response({"error": {"code": code, "message": message}}, status=status)


def _need_repr(need):
    return {"need_id": str(need.pk), "title": need.title, "category": need.category,
            "description": need.description, "quantity_needed": need.quantity_needed,
            "quantity_received": need.quantity_received, "status": need.status}


class ShelterNeedsView(APIView):
    """GET a shelter's wishlist (public); POST a new need (that shelter only)."""

    def get_permissions(self):
        return [IsShelter()] if self.request.method == "POST" else [AllowAny()]

    def get(self, request, account_id):
        qs = ShelterNeed.objects.filter(shelter_account_id=account_id)
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        qs = qs.order_by("-created_at")[:PAGE_SIZE]
        return Response({"results": [_need_repr(n) for n in qs]})

    def post(self, request, account_id):
        if str(request.user.pk) != str(account_id):
            return _err("forbidden", "A shelter can only post its own needs.", 403)
        s = NeedCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        need = ShelterNeed.objects.create(shelter_account=request.user, **s.validated_data)
        return Response({"need_id": str(need.pk)}, status=201)


class NeedPledgesView(APIView):
    """POST a pledge against an open need (any authenticated user)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, need_id):
        need = ShelterNeed.objects.filter(pk=need_id).first()
        if need is None:
            return _err("not_found", "No such need.", 404)
        if need.status != NeedStatus.OPEN:
            return _err("need_not_open", "This need is no longer open for pledges.", 409)
        s = PledgeCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        pledge = NeedPledge.objects.create(need=need, pledger_account=request.user,
                                           quantity=s.validated_data["quantity"])
        notify(need.shelter_account, "pledge_received",
               title="New pledge", body=f"Someone pledged to “{need.title}”.",
               data={"need_id": str(need.pk), "pledge_id": str(pledge.pk)})
        return Response({"pledge_id": str(pledge.pk)}, status=201)


class PledgeCancelView(APIView):
    """POST to cancel one's own still-`pledged` pledge. A delivered pledge is a recorded fact."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pledge_id):
        pledge = NeedPledge.objects.filter(pk=pledge_id,
                                           pledger_account=request.user).first()
        if pledge is None:
            return _err("not_found", "No such pledge.", 404)
        if pledge.status != PledgeStatus.PLEDGED:
            return _err("pledge_decided", "This pledge can no longer be cancelled.", 409)
        pledge.status = PledgeStatus.CANCELLED
        pledge.save(update_fields=["status"])
        return Response({"status": pledge.status})


class NeedReceivedView(APIView):
    """POST: the shelter confirms it received a pledge, entering the actual quantity."""
    permission_classes = [IsShelter]

    def post(self, request, need_id):
        need = ShelterNeed.objects.filter(pk=need_id).first()
        if need is None:
            return _err("not_found", "No such need.", 404)
        if need.shelter_account_id != request.user.pk:
            return _err("forbidden", "Only the owning shelter can confirm receipt.", 403)
        s = ReceivedSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        pledge = NeedPledge.objects.filter(pk=s.validated_data["pledge_id"],
                                           need=need).first()
        if pledge is None:
            return _err("not_found", "No such pledge for this need.", 404)
        try:
            need = apply_received(need.pk, pledge, s.validated_data["quantity_received"])
        except NeedError as e:
            return _err(str(e), "This pledge has already been decided.", 409)
        notify(pledge.pledger_account, "pledge_confirmed",
               title="Pledge received", body=f"“{need.title}” confirmed your pledge. Salamat!",
               data={"need_id": str(need.pk), "pledge_id": str(pledge.pk)})
        return Response({"need_status": need.status})
