from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.service import notify
from shelter.permissions import IsShelter
from volunteer.models import ShiftStatus, SignupStatus, VolunteerShift, VolunteerSignup
from volunteer.serializers import ShiftCreateSerializer, ShiftPatchSerializer
from volunteer.status import set_signup_status

PAGE_SIZE = 20


def _not_found(what="shift"):
    return Response({"error": {"code": "not_found", "message": f"No such {what}"}}, status=404)


def _shift_repr(shift, approved_count=None):
    if approved_count is None:
        approved_count = shift.signups.filter(status=SignupStatus.APPROVED).count()
    return {"shift_id": str(shift.pk), "type": shift.type,
            "starts_at": shift.starts_at.isoformat(), "ends_at": shift.ends_at.isoformat(),
            "capacity": shift.capacity, "status": shift.status,
            "slots_left": max(shift.capacity - approved_count, 0)}


class ShelterShiftsView(APIView):
    """US-V2 · a shelter posts and lists its own activities."""
    permission_classes = [IsShelter]

    def post(self, request):
        s = ShiftCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if d["ends_at"] <= d["starts_at"]:
            return Response({"error": {"code": "bad_window",
                                       "message": "The activity must end after it starts"}},
                            status=422)
        shift = VolunteerShift.objects.create(shelter_account=request.user, **d)
        return Response(_shift_repr(shift, approved_count=0), status=201)

    def get(self, request):
        qs = (VolunteerShift.objects.filter(shelter_account=request.user)
              .order_by("starts_at"))
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response({"results": [_shift_repr(s) for s in qs[:PAGE_SIZE]],
                         "next": None})


class ShelterShiftDetailView(APIView):
    """US-V2 · edit one activity. `closed` is terminal — never reopened."""
    permission_classes = [IsShelter]

    def patch(self, request, shift_id):
        shift = VolunteerShift.objects.filter(pk=shift_id).first()
        if shift is None:
            return _not_found()
        if shift.shelter_account_id != request.user.pk:
            return Response({"error": {"code": "not_your_shift",
                                       "message": "Only the posting shelter can edit this"}},
                            status=403)
        if shift.status == ShiftStatus.CLOSED:
            return Response({"error": {"code": "shift_closed",
                                       "message": "A closed activity cannot be changed"}},
                            status=409)
        s = ShiftPatchSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        for key, value in s.validated_data.items():
            setattr(shift, key, value)
        if shift.ends_at <= shift.starts_at:
            return Response({"error": {"code": "bad_window",
                                       "message": "The activity must end after it starts"}},
                            status=422)
        shift.save()
        return Response(_shift_repr(shift))


class ShelterShiftCancelView(APIView):
    """US-V2 · cancelling an activity cascades: the shift closes, every attached signup is
    cancelled, capacity releases, and every signed-up volunteer is notified. One transaction —
    a half-cancelled activity strands people who think they are still booked."""
    permission_classes = [IsShelter]

    def post(self, request, shift_id):
        shift = VolunteerShift.objects.filter(pk=shift_id).first()
        if shift is None:
            return _not_found()
        if shift.shelter_account_id != request.user.pk:
            return Response({"error": {"code": "not_your_shift",
                                       "message": "Only the posting shelter can cancel this"}},
                            status=403)
        if shift.status == ShiftStatus.CLOSED:
            return Response({"error": {"code": "shift_closed",
                                       "message": "This activity is already closed"}}, status=409)

        live = [SignupStatus.REQUESTED, SignupStatus.APPROVED]
        with transaction.atomic():
            shift.status = ShiftStatus.CLOSED
            shift.save(update_fields=["status", "updated_at"])
            affected = list(shift.signups.select_for_update().filter(status__in=live))
            for signup in affected:
                set_signup_status(signup, SignupStatus.CANCELLED)
                notify(signup.volunteer_account, "shift_cancelled_by_shelter",
                       title="An activity you signed up for was cancelled",
                       body="The shelter cancelled this activity.",
                       data={"shift_id": str(shift.pk)})
        return Response({"cancelled_signups": len(affected)})
