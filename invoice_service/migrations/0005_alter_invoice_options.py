# Generated by Django 4.2 on 2024-07-01 18:20

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('invoice_service', '0004_alter_invoicelineitem_surcharges_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='invoice',
            options={'permissions': [('line_manager', 'The line manager role.'), ('internal_control', 'The internal control role.'), ('head_of_finance', 'The head of finance role.'), ('snr_manager_finance', 'The snr manager  of finance role.'), ('dmd_ss', 'The DMD SS role.'), ('md', 'The managing director role.')]},
        ),
    ]
