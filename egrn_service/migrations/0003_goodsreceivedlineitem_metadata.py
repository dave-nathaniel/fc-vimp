# Generated by Django 4.2 on 2024-06-03 15:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('egrn_service', '0002_conversion_productconversion'),
    ]

    operations = [
        migrations.AddField(
            model_name='goodsreceivedlineitem',
            name='metadata',
            field=models.JSONField(default=dict),
        ),
    ]