# Generated for failed line item tracking on PurchaseOrder.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('egrn_service', '0022_stockconsumptionrecord_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaseorder',
            name='failed_line_items',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
