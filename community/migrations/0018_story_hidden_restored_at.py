"""Stories review step 14 (ST21) · `story_post.hidden_at` and `restored_at`. Nullable, no backfill: the hide and restore history of stories that already
exist lives on their flags, and a guess from `status` would be a date nobody did anything on."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("community", "0017_story_photo_position")]

    operations = [
        migrations.AddField(model_name="storypost", name="hidden_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="storypost", name="restored_at", field=models.DateTimeField(blank=True, null=True)),
    ]
