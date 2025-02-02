# Generated by Django 4.2 on 2025-02-02 00:38

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('egrn_service', '0020_remove_goodsreceivednote_posted_to_icg_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='conversion',
            options={'verbose_name': 'Products - Conversion', 'verbose_name_plural': 'Products - Conversions'},
        ),
        migrations.AlterModelOptions(
            name='goodsreceivedlineitem',
            options={'verbose_name_plural': '2.4 Goods Received Line Items'},
        ),
        migrations.AlterModelOptions(
            name='goodsreceivednote',
            options={'verbose_name_plural': '2.3 Goods Received Notes'},
        ),
        migrations.AlterModelOptions(
            name='productconfiguration',
            options={'verbose_name': 'Products - Configuration', 'verbose_name_plural': 'Products - Configurations'},
        ),
        migrations.AlterModelOptions(
            name='productsurcharge',
            options={'verbose_name': 'Products - Surcharge', 'verbose_name_plural': 'Products - Surcharges'},
        ),
        migrations.AlterModelOptions(
            name='purchaseorder',
            options={'verbose_name_plural': '2.1 Purchase Orders'},
        ),
        migrations.AlterModelOptions(
            name='purchaseorderlineitem',
            options={'verbose_name_plural': '2.2 Purchase Order Line Items'},
        ),
        migrations.AlterModelOptions(
            name='store',
            options={'verbose_name': 'Store', 'verbose_name_plural': 'Stores'},
        ),
        migrations.AlterModelOptions(
            name='surcharge',
            options={'verbose_name': 'Surcharge', 'verbose_name_plural': 'Surcharges'},
        ),
    ]
