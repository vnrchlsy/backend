"""Stories review step 6 (SQ1) · remove for good every story its author deleted 30 days ago or more.

    python manage.py purge_removed_stories

A delete is soft for 30 days (the row and its photos are kept as moderation evidence) and then hard, with the files. Its own command, like the
other purges, so a change to sweep cadence can never quietly change how fast something a person deleted is destroyed; the 30 days can only
lengthen with a later slot, never shorten.
"""
from common.management_base import SingletonCommand
from community.stories import purge_removed_stories


class Command(SingletonCommand):
    help = "Remove stories their author deleted 30 or more days ago, with their photos and files."

    def run(self, *args, **options):
        purged = purge_removed_stories()
        self.stdout.write(self.style.SUCCESS(f"purged {purged} deleted stor(y/ies)"))
