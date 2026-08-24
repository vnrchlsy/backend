"""US-F0/US-N2 · invoke all three Sagip sweeps once.

    python manage.py run_sweeps

Meant to be triggered by system cron (or run by hand in dev); no scheduler is embedded
here — see US-F0's decision to record (cron/command over Celery-beat for MVP; revisit
when Sprint 5's push delivery needs workers anyway). The sweep functions themselves don't
change no matter what ends up calling this command.
"""
from django.core.management.base import BaseCommand

from sagip.sweeps import escalate_reports, expire_offers, expire_stalled_claims


class Command(BaseCommand):
    help = "Run the Sagip sweeps: escalate unclaimed reports, expire stalled claims, expire offers."

    def handle(self, *args, **options):
        escalated = escalate_reports()
        expired = expire_stalled_claims()
        expired_offers = expire_offers()
        self.stdout.write(self.style.SUCCESS(
            f"escalated {len(escalated)} report(s), expired {len(expired)} claim(s), "
            f"expired {expired_offers} offer(s)"))
