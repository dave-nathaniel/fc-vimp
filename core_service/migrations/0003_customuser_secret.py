# Generated by Django 4.2 on 2024-09-22 17:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core_service', '0002_ledgeraccount'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='secret',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]