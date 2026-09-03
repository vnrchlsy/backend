"""US-N2 · run the §12.7 account-anonymisation purge once.

    python manage.py purge_deleted_accounts

Its own command rather than an entry in `run_sweeps`, for the same reason
`purge_expired_documents` is: **this one is irreversible.** Retention deletion should be
schedulable — and auditable — separately from the routine hourly sweeps, so that a change to
sweep cadence can never quietly change how fast personal data is destroyed. Cron it beside
the other two (US-F0's cron-over-Celery decision).
"""
from django.core.management.base import BaseCommand

from accounts.purge import anonymize_expired_accounts


class Command(BaseCommand):
    help = "Anonymize accounts whose post-deletion grace window has closed (RA 10173, §12.7)."

    def handle(self, *args, **options):
        purged = anonymize_expired_accounts()
        self.stdout.write(self.style.SUCCESS(f"anonymized {len(purged)} account(s)"))
