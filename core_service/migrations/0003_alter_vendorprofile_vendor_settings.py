# Generated by Django 4.2 on 2024-04-17 13:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core_service', '0002_vendorprofile_vendor_settings'),
    ]

    operations = [
        migrations.AlterField(
            model_name='vendorprofile',
            name='vendor_settings',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
