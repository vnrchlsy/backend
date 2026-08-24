"""US-SEC4 · identity-document retention (RA 10173 data minimization).

Decision (2026-08-23): verification documents are kept 90 days after their request's
terminal decision, then the file is deleted and `file_url` is nulled — the
`VerificationRequest`/`VerificationDocument` rows (and the decision itself) survive, so
the audit trail ("what was decided, by whom") is untouched; only the ID image goes.

Mirrors `sagip/sweeps.py`'s shape: a plain, idempotent, unit-testable function that a
management command invokes on a schedule. `needs_info`/`pending` requests are never
terminal — they have no decision to count 90 days from, so they're never touched here.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from common.storage import delete_object
from verifications.models import VerificationDocument, VerificationStatus

TERMINAL_STATUSES = (VerificationStatus.APPROVED, VerificationStatus.REJECTED)


def purge_expired_documents(now=None):
    """Null `file_url` (after deleting the backing object) on every document whose
    request reached a terminal decision more than `DOCUMENT_RETENTION_DAYS` ago.

    Idempotent: already-purged documents (`file_url=""`) are excluded from the query, so
    a document already stripped is never re-touched or double-deleted. `superseded_by`
    needs no special handling — a superseded (rejected-then-replaced) document is still
    a document of the same request, so it purges alongside its siblings on the same
    90-day clock, not on its own.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(days=settings.DOCUMENT_RETENTION_DAYS)
    docs = (VerificationDocument.objects
            .filter(verification__status__in=TERMINAL_STATUSES,
                    verification__reviewed_at__lte=cutoff)
            .exclude(file_url=""))
    purged = []
    for doc in docs:
        delete_object(doc.file_url)
        doc.file_url = ""
        doc.purged_at = now
        doc.save(update_fields=["file_url", "purged_at"])
        purged.append(doc)
    return purged
