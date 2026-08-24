from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.service import notify
from shelter.permissions import IsShelter
from volunteer.models import ShiftStatus, SignupStatus, VolunteerShift, VolunteerSignup
from volunteer.serializers import (ShiftCreateSerializer, ShiftPatchSerializer,
                                   SignupCreateSerializer)
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


class ShiftsBrowseView(APIView):
    """US-V3 · public browse. Guests may look; requesting requires an account.

    Shows `open` and `full` shifts with a future start. `full` is transient, not
    terminal — a cancelled signup flips the shift back to `open` — so a full shift is
    still a live candidate, not dead listing inventory; it's returned with
    `slots_left: 0` and the client decides how to render it (e.g. disabled). Only
    `closed` (terminal) and past shifts are excluded.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        qs = (VolunteerShift.objects
              .filter(status__in=[ShiftStatus.OPEN, ShiftStatus.FULL],
                      starts_at__gt=timezone.now())
              .order_by("starts_at"))
        shift_type = request.query_params.get("type")
        if shift_type:
            qs = qs.filter(type=shift_type)
        return Response({"results": [_shift_repr(s) for s in qs[:PAGE_SIZE]], "next": None})


class ShiftDetailView(APIView):
    """US-V3 · public shift detail, carrying `slots_left` for the '4 of 6 left' line."""
    permission_classes = [AllowAny]

    def get(self, request, shift_id):
        shift = VolunteerShift.objects.filter(pk=shift_id).first()
        if shift is None:
            return _not_found()
        return Response(_shift_repr(shift))


class ShiftSignupView(APIView):
    """US-V3 · request a shift.

    Two separate consents (see VolunteerSignup's docstring). The waiver is required and
    versioned (D-S5-1); contact-sharing is optional, per-shift, and only stamped when given.
    `UNIQUE (shift, volunteer)` is enforced by the DB and caught here so a double-tap is a
    clean 409 rather than a 500.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, shift_id):
        shift = VolunteerShift.objects.filter(pk=shift_id).first()
        if shift is None:
            return _not_found()
        if shift.status != ShiftStatus.OPEN:
            return Response({"error": {"code": "shift_not_open",
                                       "message": "This activity is not taking requests"}},
                            status=409)

        s = SignupCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if not d["waiver_accepted"]:
            return Response({"error": {"code": "waiver_required",
                                       "message": "The waiver must be accepted to join"}},
                            status=422)

        now = timezone.now()
        sharing = d["contact_share_consent"]
        try:
            signup = VolunteerSignup.objects.create(
                shift=shift, volunteer_account=request.user,
                waiver_accepted=True, waiver_accepted_at=now,
                waiver_version=settings.WAIVER_VERSION,
                contact_share_consent=sharing,
                contact_share_consent_at=now if sharing else None)
        except IntegrityError:
            return Response({"error": {"code": "already_requested",
                                       "message": "You already requested this activity"}},
                            status=409)

        notify(shift.shelter_account, "signup_requested",
               title="A volunteer requested a shift",
               body=f"{request.user.display_name} wants to join.",
               data={"shift_id": str(shift.pk), "signup_id": str(signup.pk)})
        return Response({"signup_id": str(signup.pk), "status": signup.status}, status=201)
