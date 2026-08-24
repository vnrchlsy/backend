from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.service import notify
from shelter.permissions import IsShelter
from volunteer.models import ShiftStatus, SignupStatus, VolunteerShift, VolunteerSignup
from volunteer.reliability import reliability_for
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


def _load_signup_for_shelter(signup_id, user):
    """Fetch a signup and confirm the caller's shelter posted its shift.
    Returns (signup, None) or (None, error_response)."""
    signup = (VolunteerSignup.objects.select_related("shift", "volunteer_account")
              .filter(pk=signup_id).first())
    if signup is None:
        return None, _not_found("signup")
    if signup.shift.shelter_account_id != user.pk:
        return None, Response({"error": {"code": "not_your_shift",
                                         "message": "Only the posting shelter can do this"}},
                              status=403)
    return signup, None


class SignupApproveView(APIView):
    """US-V4 · approve a request, capacity-safe.

    ⚠️ The capacity check recounts INSIDE `transaction.atomic()` after
    `select_for_update()` on the shift row. A plain count-then-write lets two concurrent
    approvals both observe a free slot and both commit, overfilling the shift — the
    difference between `capacity` being an enforced invariant and a UI-only suggestion.
    Same pattern as `sagip/views.py::ReportClaimView`'s claim exclusivity.

    ⚠️ The `not_pending` status check is ALSO re-verified under lock, on a freshly
    re-fetched signup row, after the shift lock is taken. Reading `signup.status` only
    before the lock (as the first cut of this view did) is a TOCTOU hole: two concurrent
    requests on the same signup — a double-tap, a client retry, or a decline racing an
    approve — can both pass the pre-lock check before either commits, letting a stale
    in-memory `signup` silently overwrite a DECLINED row back to APPROVED, or double-apply
    an approval. Lock order is always shift-then-signup (see SignupDeclineView, which
    takes only the signup lock and never the shift's) so the two views can never deadlock
    against each other.
    """
    permission_classes = [IsShelter]

    def post(self, request, signup_id):
        signup, error = _load_signup_for_shelter(signup_id, request.user)
        if error:
            return error

        rel = reliability_for(signup.volunteer_account)
        if rel["needs_reapproval"] and not request.data.get("acknowledged_reapproval"):
            # Server-enforced, not UI-enforced: a client must not skip the disclosure by
            # omitting it. The shelter may still approve — this is a gate, never a ban.
            return Response({"error": {"code": "reapproval_required",
                                       "message": "This volunteer has 3 no-shows in a row",
                                       "details": rel}}, status=409)

        with transaction.atomic():
            shift = (VolunteerShift.objects.select_for_update()
                     .get(pk=signup.shift_id))          # lock 1: the shift
            signup = (VolunteerSignup.objects.select_for_update()
                      .get(pk=signup.pk))                # lock 2: the signup
            if signup.status != SignupStatus.REQUESTED:
                return Response({"error": {"code": "not_pending",
                                           "message": "This request was already decided"}},
                                status=409)

            approved = shift.signups.filter(status=SignupStatus.APPROVED).count()
            if approved >= shift.capacity:
                return Response({"error": {"code": "shift_full",
                                           "message": "This activity is already full"}},
                                status=409)

            set_signup_status(signup, SignupStatus.APPROVED)
            if approved + 1 >= shift.capacity and shift.status == ShiftStatus.OPEN:
                shift.status = ShiftStatus.FULL
                shift.save(update_fields=["status", "updated_at"])

            notify(signup.volunteer_account, "shift_confirmed",
                   title="Your shift is confirmed",
                   body="The shelter approved your request.",
                   data={"shift_id": str(shift.pk), "signup_id": str(signup.pk)})
        return Response({"status": SignupStatus.APPROVED})


class SignupDeclineView(APIView):
    """US-V4 · decline a request. Always allowed, never automatic, and never silent — a
    declined volunteer must not be left in an indefinite pending state.

    ⚠️ Locks ONLY the signup row (never the shift) — declining frees no capacity, so it
    has nothing to recount. This IS still a real lock, unlike the first cut of this view:
    an approve racing the same signup takes shift-then-signup, so a lock here is required
    to close the same TOCTOU hole described on SignupApproveView (an unlocked decline
    could silently lose to, or be silently overwritten by, a concurrent approve on the
    same row). Because this view never acquires the shift lock, it can never deadlock
    against SignupApproveView's shift→signup order — it only ever waits on the signup,
    which approve also always acquires last.
    """
    permission_classes = [IsShelter]

    def post(self, request, signup_id):
        signup, error = _load_signup_for_shelter(signup_id, request.user)
        if error:
            return error

        with transaction.atomic():
            signup = (VolunteerSignup.objects.select_for_update()
                      .get(pk=signup.pk))                # the only lock this view takes
            if signup.status != SignupStatus.REQUESTED:
                return Response({"error": {"code": "not_pending",
                                           "message": "This request was already decided"}},
                                status=409)
            set_signup_status(signup, SignupStatus.DECLINED)
            notify(signup.volunteer_account, "signup_declined",
                   title="Your shift request wasn't accepted",
                   body="The shelter declined this request.",
                   data={"shift_id": str(signup.shift_id), "signup_id": str(signup.pk)})
        return Response({"status": SignupStatus.DECLINED})


# Decision 14 · a volunteer cancels FREE up to 12h before the shift; later cancels are still
# allowed but recorded on their record. Policy number, not a magic constant.
CANCEL_CUTOFF_HOURS = 12


class SignupCancelView(APIView):
    """US-V6 · a volunteer cancels their own signup.

    ⚠️ Lateness is computed SERVER-side from `cancelled_at` vs `starts_at`. A client cannot
    be trusted with the free-vs-recorded line, the same posture as the tier-derived document
    rules and US-V5's disclosure. `was_late` is derived on read, never stored as a flag.

    Cancelling releases capacity, so a `full` shift returns to `open` — under the same row
    lock the approve path uses, for consistency. `closed` stays terminal.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, signup_id):
        signup = (VolunteerSignup.objects.select_related("shift")
                  .filter(pk=signup_id).first())
        if signup is None:
            return _not_found("signup")
        if signup.volunteer_account_id != request.user.pk:
            return Response({"error": {"code": "not_your_signup",
                                       "message": "You can only cancel your own signup"}},
                            status=403)
        if signup.status not in (SignupStatus.REQUESTED, SignupStatus.APPROVED):
            return Response({"error": {"code": "not_cancellable",
                                       "message": "This signup can no longer be cancelled"}},
                            status=409)

        now = timezone.now()
        cutoff = signup.shift.starts_at - timezone.timedelta(hours=CANCEL_CUTOFF_HOURS)
        was_late = now > cutoff

        with transaction.atomic():
            shift = VolunteerShift.objects.select_for_update().get(pk=signup.shift_id)
            set_signup_status(signup, SignupStatus.CANCELLED, now=now)
            if shift.status == ShiftStatus.FULL:
                approved = shift.signups.filter(status=SignupStatus.APPROVED).count()
                if approved < shift.capacity:
                    shift.status = ShiftStatus.OPEN
                    shift.save(update_fields=["status", "updated_at"])
        return Response({"status": SignupStatus.CANCELLED, "was_late": was_late})


class ShiftRequestsView(APIView):
    """US-V5 · pending requests for one activity, each carrying its derived reliability
    block. ⚠️ Only the four aggregate numbers cross this boundary (D-S5-2) — the payload is
    built field-by-field rather than serialized off the related objects, so a stray
    `select_related` can't leak another shelter's identity into it."""
    permission_classes = [IsShelter]

    def get(self, request, shift_id):
        shift = VolunteerShift.objects.filter(pk=shift_id).first()
        if shift is None:
            return _not_found()
        if shift.shelter_account_id != request.user.pk:
            return Response({"error": {"code": "not_your_shift",
                                       "message": "Only the posting shelter can see these"}},
                            status=403)
        pending = (shift.signups.filter(status=SignupStatus.REQUESTED)
                   .select_related("volunteer_account").order_by("created_at"))
        return Response({"results": [{
            "signup_id": str(su.pk),
            "volunteer": {"display_name": su.volunteer_account.display_name},
            "requested_at": su.created_at.isoformat(),
            "reliability": reliability_for(su.volunteer_account),
        } for su in pending]})
