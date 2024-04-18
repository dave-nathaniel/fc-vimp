from django.db import models
from django.db.models import Sum

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
	
	# Computed property gross_total that returns the sum of the gross total of the invoice line items
	@property
	def gross_total(self):
		return self.invoice_line_items.aggregate(gross_total=Sum('gross_total'))['gross_total']
	
	@property
	def total_discount_amount(self):
		return self.invoice_line_items.aggregate(discount=Sum('discount_amount'))['discount']
	
	@property
	def discounted_gross_total(self):
		return self.gross_total - self.total_discount_amount
	
	@property
	def total_surcharge_amount(self):
		return self.invoice_line_items.aggregate(surcharge=Sum('surcharge_amount'))['surcharge']
	
	@property
	def net_total(self):
		return self.invoice_line_items.aggregate(net_total=Sum('net_total'))['net_total']
	
	def __str__(self):
		return f"Invoice {self.id}"


# InvoiceLineItem class
from django.db import models
from django.db.models import Sum


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
	gross_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
	discount_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
	discounted_gross_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
	surcharge_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
	net_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
	
	def calculate_gross_total(self):
		return float(self.quantity) * float(self.po_line_item.unit_price)
	
	def calculate_discount_amount(self):
		gross_total = self.calculate_gross_total()
		discount = float(self.discount)
		if self.discount_type == 'none' or self.discount == 0 or not self.discountable:
			return 0.00
		return gross_total * discount / 100 if self.discount_type == 'percentage' else discount
	
	def calculate_discounted_gross_total(self):
		return self.calculate_gross_total() - self.calculate_discount_amount()
	
	def calculate_surcharge_amount(self, surcharges):
		total_taxes = surcharges.aggregate(total_tax=Sum('rate'))['total_tax']
		total_taxes = float(total_taxes) if total_taxes is not None else 0
		return (total_taxes * self.calculate_discounted_gross_total()) / 100
	
	def calculate_net_total(self):
		return self.calculate_discounted_gross_total() - self.surcharge_amount
	
	def set_surcharge_and_net(self, surcharges):
		self.surcharge_amount = self.calculate_surcharge_amount(surcharges)
		self.net_total = self.calculate_net_total()
		super().save(update_fields=['surcharge_amount', 'net_total'])
	
	def save(self, *args, **kwargs):
		# Update the instance with the calculated values
		self.gross_total = self.calculate_gross_total()
		self.discount_amount = self.calculate_discount_amount()
		self.discounted_gross_total = self.calculate_discounted_gross_total()
		# Save the instance with the calculated fields updated
		super().save(*args, **kwargs)
	
	def __str__(self):
		return f"{self.po_line_item.product_name} ({self.quantity})"
