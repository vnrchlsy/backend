"""Stories test plan F6 · delete story photo files nobody cites.

    python manage.py sweep_story_uploads

A person who uploads a photo and never posts leaves a file in the public bucket at a guessable URL. This removes `story_photo/` files older than a
day that no story row names (never a file a row cites, whatever state its story is in). Its own command and its own lock, like the other purges.
"""
from common.management_base import SingletonCommand
from community.stories import sweep_orphan_story_uploads


class Command(SingletonCommand):
    help = "Delete story photo files older than a day that no story row cites."

    def run(self, *args, **options):
        deleted = sweep_orphan_story_uploads()
        self.stdout.write(self.style.SUCCESS(f"deleted {deleted} orphaned story upload(s)"))
