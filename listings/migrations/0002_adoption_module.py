# Hand-written (US-A1) — the interactive prompts makemigrations wants (auto_now_add
# defaults for existing rows, the listing_status->status rename) don't work in a
# non-interactive shell. RenameField (not remove+add) so existing `available`/etc.
# values survive the column rename; timezone.now() one-off defaults backfill
# created_at/updated_at on any pre-existing AdoptionListing rows.
import uuid

import django.contrib.gis.db.models.fields
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_staffprofile'),
        ('sagip', '0004_reportoffer'),
        ('listings', '0001_initial'),
    ]

    operations = [
        # ── AdoptionListing: rename + full DDL column set ──────────────────────
        migrations.RenameField(
            model_name='adoptionlisting', old_name='listing_status', new_name='status',
        ),
        migrations.AlterField(
            model_name='adoptionlisting',
            name='status',
            field=models.CharField(
                choices=[('available', 'Available'), ('pending', 'Pending'),
                        ('adopted', 'Adopted'), ('withdrawn', 'Withdrawn')],
                default='available', max_length=20),
        ),
        migrations.AlterField(
            model_name='adoptionlisting',
            name='species',
            field=models.CharField(choices=[('dog', 'Dog'), ('cat', 'Cat'), ('other', 'Other')],
                                   max_length=10),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='sex',
            field=models.CharField(blank=True,
                                   choices=[('male', 'Male'), ('female', 'Female'), ('unknown', 'Unknown')],
                                   max_length=10),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='date_of_birth',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='dob_approximate',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='size_category',
            field=models.CharField(blank=True,
                                   choices=[('small', 'Small'), ('medium', 'Medium'), ('large', 'Large')],
                                   max_length=10),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='spayed_neutered',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='vaccinated',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='walkable',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='temperament',
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='story',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='adoption_fee',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='requirements',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='geom',
            field=django.contrib.gis.db.models.fields.PointField(blank=True, geography=True,
                                                                  null=True, srid=4326),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='location_text',
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='updated_at',
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='source_report',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='adoption_listings', to='sagip.strayreport'),
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='adopted_by_account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to='accounts.account'),
        ),

        # ── Pet + PetPhoto ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Pet',
            fields=[
                ('pet_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=80)),
                ('species', models.CharField(choices=[('dog', 'Dog'), ('cat', 'Cat'), ('other', 'Other')], max_length=10)),
                ('breed', models.CharField(blank=True, max_length=80)),
                ('sex', models.CharField(choices=[('male', 'Male'), ('female', 'Female'), ('unknown', 'Unknown')], default='unknown', max_length=10)),
                ('date_of_birth', models.DateField(blank=True, null=True)),
                ('dob_approximate', models.BooleanField(default=False)),
                ('color_markings', models.CharField(blank=True, max_length=120)),
                ('weight_kg', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('size_category', models.CharField(blank=True, choices=[('small', 'Small'), ('medium', 'Medium'), ('large', 'Large')], max_length=10)),
                ('spayed_neutered', models.BooleanField(blank=True, null=True)),
                ('microchip_no', models.CharField(blank=True, max_length=40)),
                ('feeding_routine', models.TextField(blank=True)),
                ('allergies', models.TextField(blank=True)),
                ('medications', models.TextField(blank=True)),
                ('medical_conditions', models.TextField(blank=True)),
                ('temperament', models.CharField(blank=True, max_length=160)),
                ('vet_contact', models.CharField(blank=True, max_length=160)),
                ('emergency_contact', models.CharField(blank=True, max_length=160)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pets', to='accounts.account')),
            ],
            options={'db_table': 'pet'},
        ),
        migrations.CreateModel(
            name='PetPhoto',
            fields=[
                ('photo_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('url', models.TextField()),
                ('is_primary', models.BooleanField(default=False)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('pet', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='photos', to='listings.pet')),
            ],
            options={'db_table': 'pet_photo'},
        ),
        migrations.AddField(
            model_name='adoptionlisting', name='adopted_pet',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to='listings.pet'),
        ),

        # ── AdoptionListingPhoto ────────────────────────────────────────────────
        migrations.CreateModel(
            name='AdoptionListingPhoto',
            fields=[
                ('photo_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('url', models.TextField()),
                ('is_primary', models.BooleanField(default=False)),
                ('listing', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='photos', to='listings.adoptionlisting')),
            ],
            options={'db_table': 'adoption_listing_photo'},
        ),

        # ── AdoptionInquiry + AdoptionStage + AdoptionStageHistory ─────────────
        migrations.CreateModel(
            name='AdoptionInquiry',
            fields=[
                ('inquiry_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('message', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('active', 'Active'), ('adopted', 'Adopted'), ('declined', 'Declined'), ('withdrawn', 'Withdrawn')], default='active', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('listing', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='inquiries', to='listings.adoptionlisting')),
                ('adopter_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='adoption_inquiries', to='accounts.account')),
            ],
            options={'db_table': 'adoption_inquiry'},
        ),
        migrations.AddConstraint(
            model_name='adoptioninquiry',
            constraint=models.UniqueConstraint(fields=('listing', 'adopter_account'), name='uq_adoption_inquiry_pair'),
        ),
        migrations.CreateModel(
            name='AdoptionStage',
            fields=[
                ('stage_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('stage_key', models.CharField(choices=[('inquiry', 'Inquiry'), ('application', 'Application'), ('home_check', 'Home Check'), ('interview', 'Interview'), ('vet_clearance', 'Vet Clearance'), ('finalization', 'Finalization')], max_length=20)),
                ('state', models.CharField(choices=[('not_started', 'Not Started'), ('in_progress', 'In Progress'), ('done', 'Done'), ('skipped', 'Skipped')], default='not_started', max_length=20)),
                ('note', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('inquiry', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stages', to='listings.adoptioninquiry')),
            ],
            options={'db_table': 'adoption_stage'},
        ),
        migrations.AddConstraint(
            model_name='adoptionstage',
            constraint=models.UniqueConstraint(fields=('inquiry', 'stage_key'), name='uq_adoption_stage'),
        ),
        migrations.CreateModel(
            name='AdoptionStageHistory',
            fields=[
                ('history_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('stage_key', models.CharField(choices=[('inquiry', 'Inquiry'), ('application', 'Application'), ('home_check', 'Home Check'), ('interview', 'Interview'), ('vet_clearance', 'Vet Clearance'), ('finalization', 'Finalization')], max_length=20)),
                ('state', models.CharField(choices=[('not_started', 'Not Started'), ('in_progress', 'In Progress'), ('done', 'Done'), ('skipped', 'Skipped')], max_length=20)),
                ('changed_at', models.DateTimeField(auto_now_add=True)),
                ('inquiry', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stage_history', to='listings.adoptioninquiry')),
                ('changed_by_account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='accounts.account')),
            ],
            options={
                'db_table': 'adoption_stage_history',
                'indexes': [models.Index(fields=['inquiry', '-changed_at'], name='idx_adopt_stage_hist')],
            },
        ),
    ]
