# Generated by Django 4.2 on 2024-06-26 12:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('egrn_service', '0008_surcharge_productsurcharge'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaseorderlineitem',
            name='tax_rates',
            field=models.JSONField(default=list),
        ),
    ]
