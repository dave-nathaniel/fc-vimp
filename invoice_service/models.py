from django.db import models
from django.db.models import Sum
from egrn_service.models import PurchaseOrder, PurchaseOrderLineItem
from approval_service.models import Signable, Workflow


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


class InvoiceWorkflow(Workflow):
	'''
		Supporting class for the Invoice workflow. A subclass of the Workflow class.
	'''
	sign_rules = {
		# Internal Control reviews and approves all Invoices.
		"level_1": {
			"roles": ("line_manager", "internal_control"),
			"comment": "Line Manager reviews and approves Invoice less than or equal to N3Million.",
		},
		"level_2": {
			"roles": ("internal_control", "head_of_finance", "snr_manager_finance"),
			"comment": "Head of Finance /Snr Manager Finance approves Invoice from N3Million Naira to N10 Million.",
		},
		"level_3": {
			"roles": ("internal_control", "dmd_ss"),
			"comment": "DMD SS approves invoices from N10Million to 100Million",
		},
		"level_4": {
			"roles": ("internal_control", "md"),
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
		elif (invoice.gross_total > 3000000) and (invoice.gross_total <= 10000000):
			return self.sign_rules["level_2"]["roles"]
		elif (invoice.gross_total > 10000000) and (invoice.gross_total <= 100000000):
			return self.sign_rules["level_3"]["roles"]
		elif invoice.gross_total > 100000000:
			return self.sign_rules["level_4"]["roles"]
		else:
			return tuple()


class Invoice(Signable):
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
			'total_discount_amount': self.total_discount_amount,
			'discounted_gross_total': self.discounted_gross_total,
			'total_surcharge_amount': self.total_surcharge_amount,
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
		self.save(update_fields=['surcharge_amount', 'net_total'])
	
	def save(self, *args, **kwargs):
		if not self.pk:
			# Save the instance with the calculated fields updated
			self.gross_total = self.calculate_gross_total()
			self.discount_amount = self.calculate_discount_amount()
			self.discounted_gross_total = self.calculate_discounted_gross_total()
		# Save the instance with the calculated fields updated
		super(InvoiceLineItem, self).save(*args, **kwargs)
	
	def __str__(self):
		return f"{self.po_line_item.product_name} ({self.quantity})"
