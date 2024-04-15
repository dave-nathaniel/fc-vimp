from django.db import models
from egrn_service.models import PurchaseOrder, PurchaseOrderLineItem

# Create your models here.
class Surcharge(models.Model):
	code = models.IntegerField(verbose_name='Code')
	description = models.CharField(max_length=255, verbose_name='Description')
	type = models.CharField(max_length=50, blank=False, null=False, default="Value Added Tax", verbose_name='Type')
	rate = models.DecimalField(max_digits=6, decimal_places=3, verbose_name='Rate')
	last_modified = models.DateTimeField(auto_now=True, verbose_name='Last Modified')
	metadata = models.JSONField(default=dict, blank=True, null=True)
	
	def __str__(self):
		return f'{self.code} - {self.description}'


class Invoice(models.Model):
	purchase_order = models.ForeignKey(
		PurchaseOrder,
		on_delete=models.CASCADE,
		related_name="invoice",
	)
	external_document_id = models.CharField(max_length=32, blank=True, null=True)
	description = models.TextField(blank=True, null=True)
	due_date = models.DateField(blank=False, null=False)
	payment_terms = models.CharField(max_length=255, blank=True, null=True)
	payment_reason = models.CharField(max_length=255, blank=True, null=True)
	date_created = models.DateTimeField(auto_now_add=True)
	approval_metadata = models.JSONField(default=dict)
	
	def __str__(self):
		return f"Invoice {self.id}"


# InvoiceLineItem class
class InvoiceLineItem(models.Model):
	discount_types = [
		('percentage', 'Percentage'),
		('fixed', 'Fixed'),
		('none', 'None'),
	]
	invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="invoice_line_items")
	po_line_item = models.ForeignKey(PurchaseOrderLineItem, on_delete=models.CASCADE, related_name="invoice_items")
	surcharges = models.ManyToManyField(Surcharge)
	quantity = models.DecimalField(max_digits=15, decimal_places=3, null=False, blank=False, default=0.00)
	discountable = models.BooleanField(default=False)
	discount_type = models.CharField(
		max_length=10,
		blank=False,
		null=False,
		choices=discount_types,
		default=discount_types[2][0],
		verbose_name="Discount Type"
	)
	discount = models.DecimalField(
		max_digits=15,
		decimal_places=2,
		blank=False,
		null=False,
		default=0.00,
		verbose_name="Discount"
	)
	
	# Computed property gross_total that returns the gross total of the line item
	@property
	def gross_total(self):
		return float(self.quantity) * float(self.po_line_item.unit_price)
	
	# Computed property discounted_gross_total that returns the gross total of the line item after applying the discount
	@property
	def discounted_gross_total(self, ):
		...
	
	def __str__(self):
		return f"{self.po_line_item.product_name} ({self.quantity})"
