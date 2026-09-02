"""US-M2 · the moderation queue — the platform-ops admin surface for `moderation_flag`,
same pattern as the verification queue (US-R2): oldest-open-first, decisions attributed
via the staff bridge (accounts.staff.reviewer_account), never hand-edited.
"""
from django.contrib import admin, messages
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from accounts.staff import reviewer_account
from moderation.models import FlagStatus, ModerationFlag


@admin.register(ModerationFlag)
class ModerationFlagAdmin(admin.ModelAdmin):
    list_display = ("target_type", "target_id", "reporter", "reason", "status", "created_at")
    list_filter = ("status", "target_type")
    readonly_fields = ("reporter_account", "target_type", "target_id", "reason", "status",
                       "reviewed_by", "created_at", "reviewed_at")
    actions = ["mark_actioned", "mark_dismissed"]

    @admin.display(description="Reporter")
    def reporter(self, obj):
        # ⚠️ NULL = system-raised (e.g. the repeat-withdrawal rule), not a person — the
        # Sprint 2 out-of-scope note that got lost; honored here (US-M2).
        return obj.reporter_account.email if obj.reporter_account else "System"

    @admin.action(description="Mark actioned (something was done about it)")
    def mark_actioned(self, request, queryset):
        self._resolve(request, queryset, FlagStatus.ACTIONED)

    @admin.action(description="Dismiss (no action needed)")
    def mark_dismissed(self, request, queryset):
        self._resolve(request, queryset, FlagStatus.DISMISSED)

    def _resolve(self, request, queryset, status):
        reviewer = reviewer_account(request.user)
        if reviewer is None:
            self.message_user(
                request,
                "Your admin login isn't linked to a reviewer account — decision not "
                "recorded. Run `manage.py createstaff` to link it.", level=messages.ERROR)
            return
        n = queryset.update(status=status, reviewed_by=reviewer, reviewed_at=timezone.now())
        self.message_user(request, f"{n} flag(s) marked {status}.", level=messages.SUCCESS)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("reporter_account")
        # A queue, not a table: open flags (actionable) sort to the top, oldest first —
        # same rank pattern as VerificationRequestAdmin's queue.
        return qs.annotate(
            _queue_rank=Case(When(status=FlagStatus.OPEN, then=Value(0)),
                             default=Value(1), output_field=IntegerField()),
        ).order_by("_queue_rank", "created_at")

    def has_add_permission(self, request):
        # Flags are created by the API (or, per the DDL, a system rule) — never typed in.
        return False

    def has_delete_permission(self, request, obj=None):
        # A flag is the audit trail of a moderation concern — never deletable here.
        return False
