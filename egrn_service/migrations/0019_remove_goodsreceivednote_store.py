# Generated by Django 4.2 on 2024-11-28 14:51

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('egrn_service', '0018_alter_conversion_conversion_method'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='goodsreceivednote',
            name='store',
        ),
    ]