"""US-F0 · invoke both Sagip sweeps once.

    python manage.py run_sweeps

Meant to be triggered by system cron (or run by hand in dev); no scheduler is embedded
here — see US-F0's decision to record (cron/command over Celery-beat for MVP; revisit
when Sprint 5's push delivery needs workers anyway). The sweep functions themselves don't
change no matter what ends up calling this command.
"""
from django.core.management.base import BaseCommand

from sagip.sweeps import escalate_reports, expire_stalled_claims


class Command(BaseCommand):
    help = "Run the Sagip sweeps: escalate unclaimed reports, expire stalled claims."

    def handle(self, *args, **options):
        escalated = escalate_reports()
        expired = expire_stalled_claims()
        self.stdout.write(self.style.SUCCESS(
            f"escalated {len(escalated)} report(s), expired {len(expired)} claim(s)"))
