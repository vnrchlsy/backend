"""US-F0 / US-N2 / US-V7 · invoke every scheduled sweep once.

    python manage.py run_sweeps

One command, one cron entry, however many domains own sweeps. Sweeps were multiplying
across apps (sagip's three, now volunteer's reminders) and a per-app command would mean a
per-app cron line to forget. No scheduler is embedded here — US-F0's decision (cron over
Celery-beat) still stands, and D-S5-6 reconfirmed it for push.

⚠️ `purge_expired_documents` (US-SEC4) stays its own command deliberately: retention
deletion is destructive and should be schedulable — and auditable — independently of the
routine hourly sweeps.

⚠️ SingletonCommand, not BaseCommand (US-Q2 follow-up). US-Q2 measured `sweep_matches` at
11.5 minutes over 50,000 reports — 37x the time for 10x the data. Against an HOURLY cron
that fits today with ~5x of margin and stops fitting after the next 10x of growth, at which
point two of these run concurrently forever. A held lock makes the second tick a no-op
instead. See common/locks.py for why it is a database advisory lock and not `flock`.
"""
from common.management_base import SingletonCommand
from community.sweeps import award_badges
from sagip.matching import sweep_matches
from sagip.sweeps import escalate_reports, expire_offers, expire_stalled_claims
from volunteer.sweeps import remind_shifts

# (label, callable) — each returns a list of the rows it touched.
SWEEPS = [
    ("escalated", escalate_reports),
    ("expired", expire_stalled_claims),
    ("reminded", remind_shifts),
    ("badged", award_badges),
    ("matched", sweep_matches),
]


class Command(SingletonCommand):
    help = "Run every scheduled sweep: escalation, stalled claims, offer expiry, shift reminders."

    def run(self, *args, **options):
        parts = [f"{label} {len(fn())}" for label, fn in SWEEPS]
        # expire_offers returns a count, not a list — kept separate rather than forcing a
        # uniform return type on a sweep that has no rows worth handing back.
        parts.append(f"expired {expire_offers()} offer(s)")
        self.stdout.write(self.style.SUCCESS(", ".join(parts)))
