"""Stories review step 8 (ST8) · story_photo gets a `position`, and a story gets exactly one primary photo.

Order of operations matters: the column is added first, the existing rows are repaired, and only then is the constraint added (it would
fail on a story that already holds two primaries, which the old writer allowed: 200 photos all marked primary were accepted).

The repair, per story: photos are numbered 0..n-1 with the primary-marked ones first (then by `photo_id`: there is no insert time to order by, so
"the order they were sent in" cannot be recovered for stories that already exist), and the FIRST one is the primary, whether none, one or several were marked.
"""
from django.db import migrations, models


def fix_story_photos(apps, schema_editor):
    Photo = apps.get_model("community", "StoryPhoto")
    current, position = None, 0
    for photo in Photo.objects.order_by("story_id", "-is_primary", "photo_id").iterator():
        if photo.story_id != current:
            current, position = photo.story_id, 0
        primary = position == 0
        if photo.position != position or photo.is_primary != primary:
            photo.position, photo.is_primary = position, primary
            photo.save(update_fields=["position", "is_primary"])
        position += 1


class Migration(migrations.Migration):

    dependencies = [
        ('community', '0016_story_removed'),
    ]

    operations = [
        migrations.AddField(
            model_name='storyphoto',
            name='position',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(fix_story_photos, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='storyphoto',
            constraint=models.UniqueConstraint(condition=models.Q(('is_primary', True)), fields=('story',), name='uq_story_photo_one_primary'),
        ),
    ]
