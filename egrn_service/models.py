from django.db import models


class Vendor(models.Model):
	name = models.CharField(max_length=100)
	# Add other fields as needed

	def __str__(self):
		return self.name

class PurchaseOrder(models.Model):
	vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE)
	date = models.DateField()
	# Add other fields as needed

	def __str__(self):
		return f"PO-{self.id} from {self.vendor.name}"

class PurchaseOrderLineItem(models.Model):
	purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='line_items')
	product_name = models.CharField(max_length=100)
	quantity = models.IntegerField()
	price = models.DecimalField(max_digits=10, decimal_places=2)
	# Add other fields as needed

	def __str__(self):
		return f"{self.product_name} ({self.quantity})"

class Store(models.Model):
	store_name = models.CharField(max_length=255)
	icg_warehouse_name = models.CharField(max_length=255, null=True, blank=True)
	icg_warehouse_code = models.CharField(max_length=20, unique=True)
	byd_cost_center_code = models.CharField(max_length=20, unique=True)

	def __str__(self):
		return f"{self.store_name.upper()} | {self.icg_warehouse_name.upper()}"

class GoodsReceivedNote(models.Model):
	purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE)
	store = models.ForeignKey(Store, on_delete=models.CASCADE)
	received_date = models.DateField()
	# Add other fields as needed

	def __str__(self):
		return f"e-GRN for PO-{self.purchase_order.id} at {self.store.name}"
