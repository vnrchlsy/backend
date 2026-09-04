"""US-Q2 follow-up · every cron-invoked command is overlap-guarded — checked against the
actual crontab, not against a list someone remembered to update.

`common/management_base.py` claims a command added later "gets the guard by inheriting".
That is only true if somebody notices to inherit. This reads `deploy/cron.d/kupkop` — the
file that decides what actually runs on a schedule — and asserts every command it invokes
is a `SingletonCommand`. Add a cron line for an unguarded command and this goes red, which
is the only version of that claim worth making.
"""
import os
import re

import pytest
from django.core.management import load_command_class

from common.management_base import SingletonCommand

CRONTAB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "deploy", "cron.d", "kupkop")

# manage.py <command>, ignoring the leading schedule/user/path noise on a cron line.
INVOCATION = re.compile(r"manage\.py\s+([a-z_][a-z0-9_]*)")


def scheduled_commands():
    with open(CRONTAB) as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    return sorted({m.group(1) for ln in lines for m in INVOCATION.finditer(ln)})


def test_the_crontab_is_where_we_think_it_is():
    # If this file moves or is renamed, the parametrized test below would silently collect
    # ZERO cases and pass — a guard that guards nothing, which is the failure this whole
    # story is about.
    assert os.path.exists(CRONTAB), CRONTAB
    assert len(scheduled_commands()) >= 3, scheduled_commands()


@pytest.mark.parametrize("name", scheduled_commands())
def test_every_scheduled_command_refuses_to_run_twice_at_once(name):
    app = {"run_sweeps": "sagip", "purge_deleted_accounts": "accounts",
           "purge_expired_documents": "verifications"}.get(name)
    assert app, (f"'{name}' is scheduled in deploy/cron.d/kupkop but this test does not know "
                 "which app owns it — add it here, and give it a SingletonCommand base.")
    cls = load_command_class(app, name)
    assert isinstance(cls, SingletonCommand), (
        f"'{name}' runs on a schedule but is not a SingletonCommand, so two ticks can "
        "overlap. Subclass common.management_base.SingletonCommand and rename handle() "
        "to run().")
