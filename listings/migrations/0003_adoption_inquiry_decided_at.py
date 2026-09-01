from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0002_adoption_module'),
    ]

    operations = [
        migrations.AddField(
            model_name='adoptioninquiry',
            name='decided_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
