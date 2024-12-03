from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from egrn_service.models import PurchaseOrder, PurchaseOrderLineItem, GoodsReceivedLineItem, GoodsReceivedNote
from approval_service.models import Signable, Workflow


# Create your models here.
class InvoiceWorkflow(Workflow):
	'''
		Supporting class for the Invoice workflow. A subclass of the Workflow class.
	'''
	sign_rules = {
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
		},
	}
	
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
		# Get the line item fields excluding the surcharges field, we can't directly "get" the ManyToMany surcharges field
		line_item_fields = [field for field in self.__get_line_item_fields__() if field.name not in ['surcharges']]
		return [[(lambda x, y: getattr(x, y))(line_item, field.name) for field in line_item_fields] for line_item in
				self.invoice_line_items.all()]
	
	def set_identity(self):
		invoice_values = {
			'id': self.id,
			'external_document_id': self.external_document_id,
			'description': self.description,
			'due_date': self.due_date,
			'payment_terms': self.payment_terms,
			'payment_reason': self.payment_reason,
			'date_created': self.date_created,
			'gross_total': self.gross_total,
			'total_tax_amount': self.total_tax_amount,
			'net_total': self.net_total,
			'signatories': self.signatories
		}
		line_item_attrs = self.__get_line_item_attrs__()
		# Convert values to strings
		combined_line_item_values = ''.join([''.join([str(i) for i in item]) for item in line_item_attrs])
		invoice_values = ''.join([str(i) for i in invoice_values.values()])
		# Concatenate the line item values to the invoice values
		identity_data = invoice_values + combined_line_item_values
		# Set the identity_data property, to be hashed and used as a seal
		self.identity_data = identity_data.replace(' ', '')
	
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
		if self.quantity < 1:
			raise ValidationError("Invoice quantity must be greater than 0")
		if self.quantity > self.get_invoiceable_quantity():
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
