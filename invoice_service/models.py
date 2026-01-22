from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from egrn_service.models import PurchaseOrder, PurchaseOrderLineItem, GoodsReceivedLineItem, GoodsReceivedNote
from approval_service.models import Signable, Workflow

import json
from decimal import Decimal
import hashlib

from django_q.tasks import async_task


WORKFLOW_RULES = {
	# Internal Control reviews and approves all Invoices.
	"level_1": {
		"roles": ("accounts_payable", "line_manager", "internal_control"),
		"comment": "Line Manager reviews and approves Invoice less than or equal to N3Million.",
	},
	"level_2": {
		"roles": ("accounts_payable", "line_manager", "internal_control", "snr_manager_finance"),
		"comment": "Head of Finance /Snr Manager Finance approves Invoice from N3Million Naira to N5 Million.",
	},
	"level_3": {
		"roles": ("accounts_payable", "line_manager", "internal_control", "snr_manager_finance", "head_of_finance"),
		"comment": "Head of Finance /Snr Manager Finance approves Invoice from N5Million Naira to N10 Million.",
	},
	"level_4": {
		"roles": ("accounts_payable", "line_manager", "internal_control", "snr_manager_finance", "head_of_finance", "dmd_ss"),
		"comment": "DMD SS approves invoices from N10Million to 100Million",
	},
	"level_5": {
		"roles": ("accounts_payable", "line_manager", "internal_control", "snr_manager_finance", "head_of_finance", "dmd_ss", "md"),
		"comment": "MD approves PO/DPs from N100Million",
	}
}

# Create your models here.
class InvoiceWorkflow(Workflow):
	'''
		Supporting class for the Invoice workflow. A subclass of the Workflow class.
	'''
	sign_rules = WORKFLOW_RULES
	
	def __init__(self, invoice):
		self.name = "Invoice Workflow"
		super().__init__(self.name, invoice)
	
	def get_signatories(self) -> tuple:
		invoice = self.signable
		if invoice.gross_total <= 3000000:
			return self.sign_rules["level_1"]["roles"]
		elif (invoice.gross_total > 3000000) and (invoice.gross_total <= 5000000):
			return self.sign_rules["level_2"]["roles"]
		elif (invoice.gross_total > 5000000) and (invoice.gross_total <= 10000000):
			return self.sign_rules["level_3"]["roles"]
		elif (invoice.gross_total > 10000000) and (invoice.gross_total <= 100000000):
			return self.sign_rules["level_4"]["roles"]
		elif invoice.gross_total > 100000000:
			return self.sign_rules["level_5"]["roles"]
		else:
			return tuple()


class Invoice(Signable):
	purchase_order = models.ForeignKey(
		PurchaseOrder,
		on_delete=models.CASCADE,
		related_name="invoices",
	)
	grn = models.ForeignKey(
		GoodsReceivedNote,
		on_delete=models.CASCADE,
		related_name="grn",
		null=True, blank=True
	)
	external_document_id = models.CharField(max_length=32, blank=True, null=True)
	description = models.TextField(blank=True, null=True)
	due_date = models.DateField(blank=False, null=False)
	payment_terms = models.CharField(max_length=255, blank=True, null=True)
	payment_reason = models.CharField(max_length=255, blank=True, null=True)
	date_created = models.DateTimeField(auto_now_add=True)
	
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
	def total_tax_amount(self):
		return self.invoice_line_items.aggregate(tax=Sum('tax_amount'))['tax']
	
	@property
	def net_total(self):
		return self.invoice_line_items.aggregate(net_total=Sum('net_total'))['net_total']
	
	class Meta:
		permissions = [
			('accounts_payable', 'The accounts payable role.'),
			('line_manager', 'The line manager role.'),
			('internal_control', 'The internal control role.'),
			('head_of_finance', 'The head of finance role.'),
			('snr_manager_finance', 'The snr manager  of finance role.'),
			('dmd_ss', 'The DMD SS role.'),
			('md', 'The managing director role.'),
		]
	
	def __get_line_item_fields__(self):
		return self.invoice_line_items.model._meta.get_fields()
	
	def __get_line_item_attrs__(self):
		"""
		Optimized method to get line item attributes for identity hashing.
		Returns only the essential fields needed for hash calculation.
		"""
		# Fetch line items in a single query with select_related for efficiency
		line_items = self.invoice_line_items.select_related('po_line_item', 'grn_line_item').order_by('id')

		# print(self.invoice_line_items.all())
		# Build a list of essential attributes per line item
		# Only include immutable/essential fields for the hash
		line_item_data = []
		for item in line_items:
			line_item_data.append({
				'id': item.id,
				'po_line_item_id': item.po_line_item_id,
				'grn_line_item_id': item.grn_line_item_id if item.grn_line_item else None,
				'quantity': str(item.quantity),
				'net_total': str(item.net_total),
				'gross_total': str(item.gross_total),
				'tax_amount': str(item.tax_amount),
			})

		return line_item_data
	
	def on_workflow_start(self) -> bool:
		from .serializers import InvoiceSerializer
		# Asynchronously send an email notification to the first signatory.
		serialized = InvoiceSerializer(self).data
		async_task('vimp.tasks.notify_approval_required', serialized, q_options={
			'task_name': f'Notify-Next-Signatory-For-Invoice-{self.id}',
		})
		return True
	
	def on_workflow_next(self) -> bool:
		from .serializers import InvoiceSerializer
		# Asynchronously send an email notification to the next signatory.
		serialized = InvoiceSerializer(self).data
		async_task('vimp.tasks.notify_approval_required', serialized, q_options={
			'task_name': f'Notify-Next-Signatory-For-Invoice-{serialized.get("id")}',
		})
		return True
	
	def on_workflow_end(self) -> bool:
		# Complete the ledger posting process for the GRN if the invoice is accepted.
		if self.is_accepted:
			async_task('vimp.tasks.create_invoice_on_byd', self, q_options={
				'task_name': f'Create-Invoice-{self.id}-on-ByD',
			})
			# async_task('vimp.tasks.post_to_gl', {
			# 	'grn': self.grn,
			# 	'action': 'invoice_approval', # This must be one of either 'receipt' or 'invoice_approval'.
			# }, q_options={
			# 	'task_name': f'Approved-Invoice-GL-Entry-For-GRN-{self.grn.grn_number}',
			# })
		return True
	
	def set_identity(self):
		"""
		Optimized method to calculate identity hash for the invoice.
		Uses a single aggregation query and JSON serialization for consistency.
		"""

		# Prefer annotated values when the parent queryset supplied them, otherwise fallback to one aggregation query
		if hasattr(self, 'gross_total_annotated') and self.gross_total_annotated is not None:
			aggregates = {
				'gross_total': self.gross_total_annotated,
				'tax_amount': self.total_tax_amount_annotated,
				'net_total': self.net_total_annotated,
			}
		else:
			# Single optimized query to get all aggregated values at once
			aggregates = self.invoice_line_items.aggregate(
				gross_total=Sum('gross_total'),
				tax_amount=Sum('tax_amount'),
				net_total=Sum('net_total')
			)

		# Convert Decimal to string for JSON serialization
		def decimal_to_str(obj):
			if isinstance(obj, Decimal):
				return str(obj)
			return obj

		# Build invoice data dictionary with explicit ordering
		invoice_data = {
			'id': self.id,
			'external_document_id': self.external_document_id or '',
			'description': self.description or '',
			'due_date': self.due_date.isoformat() if self.due_date else '',
			'payment_terms': self.payment_terms or '',
			'payment_reason': self.payment_reason or '',
			'date_created': self.date_created.isoformat() if self.date_created else '',
			'gross_total': decimal_to_str(aggregates['gross_total']),
			'total_tax_amount': decimal_to_str(aggregates['tax_amount']),
			'net_total': decimal_to_str(aggregates['net_total']),
			'signatories': self.signatories if isinstance(self.signatories, list) else []
		}

		# Fetch line item data using .values() to avoid full model instantiation
		line_items_qs = (
			self.invoice_line_items
			.select_related('po_line_item', 'grn_line_item')
			.values(
				'id',
				'po_line_item_id',
				'grn_line_item_id',
				'quantity',
				'net_total',
				'gross_total',
				'tax_amount',
			)
			.order_by('id')
		)
		line_item_data = [
			{
				'id': li['id'],
				'po_line_item_id': li['po_line_item_id'],
				'grn_line_item_id': li['grn_line_item_id'],
				'quantity': str(li['quantity']),
				'net_total': str(li['net_total']),
				'gross_total': str(li['gross_total']),
				'tax_amount': str(li['tax_amount']),
			}
			for li in line_items_qs
		]

		# Combine into a single data structure
		identity_dict = {
			'invoice': invoice_data,
			'line_items': line_item_data
		}

		# Produce a deterministic hash of the identity dict without persisting the verbose JSON
		identity_json = json.dumps(identity_dict, sort_keys=True, separators=(',', ':'))
		self.identity_data = hashlib.sha256(identity_json.encode('utf-8')).hexdigest()
	
	def set_signatories(self):
		# The workflow object. This is a custom workflow that is defined for the invoice model
		workflow = InvoiceWorkflow(self)
		self.signatories = list(workflow.get_signatories())
		self.current_pending_signatory = self.signatories[0] if self.signatories else None
	
	def seal_class(self, ):
		# Set the signatories based on the workflow
		self.set_signatories()
		# Set the identity data
		self.set_identity()
		# Update the digest and save the digest of the identity data, thereby sealing the class to detect any form of modification.
		if super().update_digest():
			return True
		return False
	
	def __str__(self):
		return f"Invoice {self.id}"
	
	class Meta:
		verbose_name = "3.1 Invoice"
		verbose_name_plural = "3.1 Invoices"


class InvoiceLineItem(models.Model):
	invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="invoice_line_items")
	po_line_item = models.ForeignKey(PurchaseOrderLineItem, on_delete=models.CASCADE)
	grn_line_item = models.ForeignKey(GoodsReceivedLineItem, on_delete=models.CASCADE, null=True,
									  blank=True, related_name="invoice_items")
	quantity = models.DecimalField(max_digits=15, decimal_places=3, null=False, blank=False, default=0.00)
	net_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
	gross_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
	tax_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
	
	def calculate_tax_amount(self, ):
		tax_rates = sum([rate['rate'] for rate in self.po_line_item.tax_rates])
		tax_amount = self.calculate_net_total() * (tax_rates / 100)
		return round(tax_amount, 3)
	
	def calculate_net_total(self):
		return float(self.quantity) * float(self.po_line_item.unit_price)
	
	def calculate_gross_total(self):
		return self.calculate_net_total() + self.calculate_tax_amount()
	
	def get_invoiced_quantity(self):
		'''
			Return the quantity already invoiced for this line item.
		'''
		invoiced = InvoiceLineItem.objects.filter(grn_line_item=self.grn_line_item)
		invoiced_quantity = invoiced.aggregate(quantity=Sum('quantity'))['quantity']
		invoiced_quantity = invoiced_quantity or 0.00
		return float(invoiced_quantity)
	
	def get_invoiceable_quantity(self):
		'''
			Return the quantity that can be invoiced for this line item.
		'''
		invoiced = self.get_invoiced_quantity()
		return float(self.po_line_item.delivered_quantity) - invoiced
		
	def clean(self, ):
		if self.quantity < 0.00:
			raise ValidationError("Invoice quantity must be greater than 0")
		if float(self.quantity) > self.get_invoiceable_quantity():
			raise ValidationError(f"Invoice quantity exceeds the outstanding invoiceable quantity ({self.get_invoiceable_quantity()})")
	
	def save(self, *args, **kwargs):
		# Save the instance with the calculated fields updated
		self.quantity = self.grn_line_item.quantity_received
		self.gross_total = self.calculate_gross_total()
		self.net_total = self.calculate_net_total()
		self.tax_amount = self.calculate_tax_amount()
		self.clean()
		# self.po_line_item = self.grn_line_item.purchase_order_line_item
		super(InvoiceLineItem, self).save(*args, **kwargs)
	
	def __str__(self):
		return f"{self.po_line_item.product_name} ({self.quantity})"
	
	class Meta:
		verbose_name = "3.2 Invoice Line Item"
		verbose_name_plural = "3.2 Invoice Line Items"