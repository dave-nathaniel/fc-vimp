# Generated by Django 4.2 on 2024-06-25 17:44

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('egrn_service', '0006_rename_product_code_purchaseorderlineitem_product_id_and_more'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ProductSurcharge',
        ),
    ]