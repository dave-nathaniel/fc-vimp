from django.db import models
from egrn_service.models import PurchaseOrder, PurchaseOrderLineItem
from core_service.models import VendorProfile
from datetime import datetime


# Create your models here.
class Surcharge(models.Model):
	code = models.IntegerField(max_length=5, verbose_name='Code')
	description = models.CharField(max_length=255, verbose_name='Description')
	type = models.CharField(max_length=50, blank=False, null=False, default="Value Added Tax", verbose_name='Type')
	rate = models.DecimalField(max_digits=6, decimal_places=3, verbose_name='Rate')
	last_modified = models.DateTimeField(auto_now=True, verbose_name='Last Modified')
	metadata = models.JSONField(default=dict, blank=True, null=True)
	
	def __str__(self):
		return f'{self.code} - {self.description}'


class Invoice(models.Model):
	purchase_order = models.OneToOneField(
		PurchaseOrder,
		on_delete=models.CASCADE,
		related_name="invoice",
	)
	supplier = models.ForeignKey(
		VendorProfile,
		on_delete=models.CASCADE,
		related_name="invoices",
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
	invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="invoive_line_items")
	po_line_item = models.ForeignKey(PurchaseOrderLineItem, on_delete=models.CASCADE)
	quantity = models.DecimalField(max_digits=15, decimal_places=3, null=False, blank=False, default=0.00)
	surcharges = models.ManyToManyField(Surcharge)
	discountable = models.BooleanField(default=False)
	discount_type = models.CharField(
		max_length=10,
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
	
	def __str__(self):
		return f"{self.description} ({self.quantity})"
