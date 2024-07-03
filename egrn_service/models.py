import logging
import inspect
from . import converters
from django.db import models
from django.db.utils import IntegrityError
from core_service.models import VendorProfile
from byd_service.rest import RESTServices
from byd_service.util import to_python_time
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Sum
from django.forms.models import model_to_dict


# Create your models here.
class Surcharge(models.Model):
	code = models.IntegerField(verbose_name='Code')
	description = models.CharField(max_length=255, verbose_name='Description')
	type = models.CharField(max_length=50, blank=False, null=False, default="Value Added Tax", verbose_name='Type')
	rate = models.FloatField(verbose_name='Rate')
	last_modified = models.DateTimeField(auto_now=True, verbose_name='Last Modified')
	metadata = models.JSONField(default=dict, blank=True, null=True)
	
	def __str__(self):
		return f'{self.code} - {self.description}'


class ProductSurcharge(models.Model):
	'''
		Associates a product with a surcharge.
	'''
	
	product_id = models.CharField(max_length=32, blank=False, null=False) # The ByD Product ID
	surcharge = models.ForeignKey(Surcharge, on_delete=models.CASCADE, related_name='product_surcharge')
	
	class Meta:
		unique_together = ('product_id', 'surcharge')


# Initialize REST services
byd_rest_services = RESTServices()

def get_conversion_methods():
	methods = inspect.getmembers(converters, inspect.isfunction)
	return [(name, name) for name, func in methods]


class Store(models.Model):
	store_name = models.CharField(max_length=255)
	icg_warehouse_name = models.CharField(max_length=255, null=True, blank=True)
	icg_warehouse_code = models.CharField(max_length=20, unique=True)
	byd_cost_center_code = models.CharField(max_length=20, unique=True)
	
	def __str__(self):
		return f"{self.store_name.upper()} | {self.icg_warehouse_name.upper()}"


class PurchaseOrder(models.Model):
	vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE)
	object_id = models.CharField(max_length=32, blank=False, null=False, unique=True)
	po_id = models.IntegerField(blank=False, null=False, unique=True)
	total_net_amount = models.DecimalField(max_digits=15, decimal_places=3, blank=False, null=False)
	date = models.DateField()
	metadata = models.JSONField(default=dict)
	
	delivery_status_code = [('1', 'Not Delivered'), ('2', 'Partially Delivered'), ('3', 'Completely Delivered')]
	invoicing_status_code = [('1', 'Not Started'), ('2', 'In Process'), ('3', 'Finished')]
	
	@property
	def delivery_status(self, ):
		status = self.delivery_status_code[0]
		# Retrieve all related PurchaseOrderLineItems
		order_items = self.line_items.all()
		# Check if all PurchaseOrderLineItems are completed
		partially_delivered_quantities = [item.delivery_status[0] == '2' for item in order_items]
		completely_delivered_quantities = [item.delivery_status[0] == '3' for item in order_items]
		if all(completely_delivered_quantities):
			status = self.delivery_status_code[2]
		elif any(partially_delivered_quantities) or any(completely_delivered_quantities):
			status = self.delivery_status_code[1]
			
		return status
	
	def create_purchase_order(self, po):
		# Get the vendor's profile (if they've completed their onboarding), or create a profile that will be attached
		# to the vendor whenever they complete their onboarding.
		supplier = po.get("Supplier")
		vendor, created = VendorProfile.objects.get_or_create(byd_internal_id=supplier["PartyID"])
		if created:
			vendor.byd_metadata = supplier
			vendor.save()
		
		self.vendor = vendor
		self.object_id = po["ObjectID"]
		self.total_net_amount = po["TotalNetAmount"]
		self.po_id = po["ID"]
		self.date = to_python_time(po["LastChangeDateTime"])
		po_items = po.pop("Item")
		self.metadata = po
		self.save()
		
		for line_item in po_items:
			self.__create_line_items__(line_item)
		
		return self
	
	def __create_line_items__(self, line_item):
		po_line_item = PurchaseOrderLineItem()
		
		po_line_item.purchase_order = self
		po_line_item.object_id = line_item["ObjectID"]
		po_line_item.product_name = line_item["Description"]
		po_line_item.product_id = line_item["ProductID"]
		po_line_item.quantity = float(line_item["Quantity"])
		po_line_item.unit_price = line_item["ListUnitPriceAmount"]
		po_line_item.unit_of_measurement = line_item["QuantityUnitCodeText"]
		po_line_item.metadata = line_item
		
		po_line_item.save()
	
	def __str__(self):
		return f"PO-{self.po_id}"


class PurchaseOrderLineItem(models.Model):
	purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='line_items')
	object_id = models.CharField(max_length=32, blank=False, null=False, unique=True)
	product_id = models.CharField(max_length=32, blank=False, null=False)
	product_name = models.CharField(max_length=100)
	quantity = models.DecimalField(max_digits=15, decimal_places=3)
	unit_price = models.DecimalField(max_digits=15, decimal_places=3)
	tax_rates = models.JSONField(default=list)
	unit_of_measurement = models.CharField(max_length=32, blank=False, null=False)
	metadata = models.JSONField(default=dict)
	
	@property
	def delivery_status(self):
		if self.delivered_quantity == 0:
			return self.purchase_order.delivery_status_code[0]
		elif (self.delivered_quantity > 0) and (self.delivered_quantity < self.quantity):
			return self.purchase_order.delivery_status_code[1]
		elif self.delivered_quantity == self.quantity:
			return self.purchase_order.delivery_status_code[2]
	
	@property
	def delivered_quantity(self, ):
		# Access related GoodsReceivedLineItem instances and calculate total received quantity
		delivered_quantity = self.grn_line_item.aggregate(total_received=Sum('quantity_received'))['total_received']
		return delivered_quantity or 0.00
	
	@property
	def extra_fields(self, ):
		# If the product ID is defined in the ProductConversion model, return the conversion fields
		try:
			product_conversion = ProductConversion.objects.get(product_id=self.metadata["ProductID"])
			return product_conversion.conversion.conversion_field
		except ObjectDoesNotExist:
			return []
	
	def __get_tax_rate__(self,):
		# Calculate the gross amount and tax rate based on the metadata['NetAmount'] and metadata['TaxAmount'] keys.
		net_amount = float(self.metadata['NetAmount'])
		tax_amount = float(self.metadata['TaxAmount'])
		gross_amount = net_amount + tax_amount
		tax_percentage =  (tax_amount / net_amount) * 100
		
		return round(tax_percentage, 1)
	
	def save(self, ):
		try:
			# Get the surcharge with the tax rate
			surcharge = Surcharge.objects.filter(rate=self.__get_tax_rate__())
			self.tax_rates = [model_to_dict(i) for i in surcharge]
		except ObjectDoesNotExist:
			# If the surcharge percent is not found, create a new surcharge with the tax rate
			pass
			
		super().save()
	
	def __str__(self):
		return f"{self.product_name} ({self.quantity})"


class GoodsReceivedNote(models.Model):
	purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='purchase_order')
	store = models.ForeignKey(Store, on_delete=models.CASCADE)
	grn_number = models.IntegerField(blank=False, null=False, unique=True)
	created = models.DateField(auto_now_add=True)
	
	def save(self, *args, **kwargs):
		grn_data = kwargs.pop('grn_data')
		po_id = grn_data['po_id']
		# Set the store where this GRN is being received
		self.store = Store.objects.all()[0]
		try:
			# Try to retrieve an object by a specific field
			# If the object is found, you can work with it here
			self.purchase_order = PurchaseOrder.objects.get(po_id=po_id)
		except ObjectDoesNotExist:
			# Create the Purchase Order
			po_data = byd_rest_services.get_purchase_order_by_id(po_id)
			new_po = PurchaseOrder()
			self.purchase_order = new_po.create_purchase_order(po_data)
		except Exception as e:
			raise e
		
		# Create the GRN Number by appending a number to the end of the PO ID
		self.grn_number = int(str(po_id) + '1')
		# Progressively increment the GRN number until it is unique
		saved_as_grn = False # Boolean to control the loop
		while not saved_as_grn:
			try:
				super().save(*args, **kwargs)
				saved_as_grn = True
			except IntegrityError:
				self.grn_number = int(self.grn_number) + 1
			except Exception as e:
				logging.error(e)
				raise e
		# If none of the line items were created (meaning there was an error with all the line items),
		# then delete the GRN altogether and return False
		try:
			self.__create_line_items__(grn_data.get("recievedGoods"))
		except Exception as e:
			self.delete()
			raise e
		# Return True if any line items were created
		return self
	
	def __create_line_items__(self, line_items):
		# An object to hold the status of line items that were created
		created_line_items = {}
		for line_item in line_items:
			try:
				grn_line_item = GoodsReceivedLineItem()
				# Get the purchase order line item that corresponds to this line item from the purchase order of this Goods Received Note
				grn_line_item.purchase_order_line_item = PurchaseOrderLineItem.objects.get(purchase_order=self.purchase_order,
																 object_id=line_item["itemObjectID"])
				grn_line_item.grn = self
				grn_line_item.quantity_received = round(float(line_item["quantityReceived"]),3)
				grn_line_item.save(data=line_item)
				created_line_items[line_item['itemObjectID']] = True
			except Exception as e:
				logging.error(f"{line_item['itemObjectID']}: {e}")
				created_line_items[line_item['itemObjectID']] = False
				raise e
		# If any of the line items were created, return True.
		return any(created_line_items.values())
	
	def __str__(self):
		return f"e-GRN #{self.grn_number}"


class GoodsReceivedLineItem(models.Model):
	grn = models.ForeignKey(GoodsReceivedNote, on_delete=models.CASCADE, related_name='line_items')
	purchase_order_line_item = models.ForeignKey(PurchaseOrderLineItem, on_delete=models.CASCADE,
												 related_name='grn_line_item')
	quantity_received = models.DecimalField(max_digits=15, decimal_places=3, default=0.000)
	net_value_received = models.DecimalField(max_digits=15, decimal_places=3)
	gross_value_received = models.DecimalField(max_digits=15, decimal_places=3)
	metadata = models.JSONField(default=dict, blank=True, null=True)
	date_received = models.DateField(auto_now=True)
	
	def net_value(self):
		return float(self.quantity_received) * float(self.purchase_order_line_item.unit_price)
	
	def calculate_tax_amount(self):
		'''
			Calculate the tax amount by getting the tax percentages from the purchase_order_line_item.tax_rates,
			and adding it to the net value received.
		'''
		tax_rates = sum([rate['rate'] for rate in self.purchase_order_line_item.tax_rates])
		tax_amount = self.net_value() * (tax_rates / 100)
		return round(tax_amount, 3)
	
	def clean(self):
		# Get the sum of the quantity received for this item by adding up the quantity received
		# of all GRN line items for this particular PO line item.
		grns_raised_for_this = self.get_grn_for_po_line(self.purchase_order_line_item.object_id)
		total_received = grns_raised_for_this.aggregate(total_sum=Sum('quantity_received'))['total_sum']
		total_received = total_received or 0.00
		# Get the quantity that is being received for this item.
		quantity_to_receive = self.quantity_received
		# Check that quantity to receive is greater than 0.
		if quantity_to_receive <= 0:
			raise ValidationError("Quantity received must be greater than 0.")
		# Get the outstanding delivery for this item.
		outstanding_quantity = float(self.purchase_order_line_item.quantity) - float(total_received)
		# Check to see if there is any outstanding delivery for this item.
		if outstanding_quantity == 0:
			raise ValidationError("This item has been completely delivered.")
		# Get the sum of the quantity received and the total quantity received for this item.
		sum_quantity = float(quantity_to_receive) + float(total_received)
		# Check to see if the quantity received is greater than the outstanding quantity.
		if float(sum_quantity) > float(self.purchase_order_line_item.quantity):
			raise ValidationError(
				f"Quantity received ({quantity_to_receive}) is greater than outstanding delivery quantity ({outstanding_quantity}).")
		
	def convert_product(self, data):
		# Get the product_id of the product being saved from the po line item metadata`
		product_id = self.purchase_order_line_item.metadata.get('ProductID')
		try:
			# Get conversion methods defined for this product
			conversion_method = ProductConversion.objects.get(product_id=product_id).conversion.conversion_method
		except ObjectDoesNotExist:
			return False
		# Get the conversion method name from the instance
		method_name = conversion_method
		# Get all the functions from the conversion_methods module
		methods = dict(inspect.getmembers(converters, inspect.isfunction))
		# Get the specific method to call
		method_to_call = methods.get(method_name)
	
		if method_to_call:
			try:
				input_fields = data.get('extra_fields')
				# Call the conversion method with the Product instance
				result = method_to_call(input_fields=input_fields)
				# If any items in the result dict is an attribute of this class, remove it from the result dict and set it to the instance
				for key, value in result.items():
					if hasattr(self, key):
						setattr(self, key, value)
					else:
						self.metadata[key] = value
			except Exception as e:
				logging.error(f"Error converting product with method {method_name}: {e}")
				raise e
		else:
			logging.error(f"conversion method {method_name} not found in conversion_methods module")
	
	def save(self, *args, **kwargs):
		"""
			Saves the instance to the database.
		"""
		try:
			self.convert_product(data=kwargs.get('data'))
		except Exception as e:
			logging.error(f"Error converting product: {e}")
			
		# Calculate the net and gross value received
		self.net_value_received = self.net_value()
		self.gross_value_received = self.net_value_received + self.calculate_tax_amount()
		
		self.clean()
		
		return super().save()
	
	def get_grn_for_po_line(self, object_id):
		"""
			Returns the Goods Received Note for this line item.
		"""
		line_items = GoodsReceivedLineItem.objects.filter(purchase_order_line_item__object_id=object_id)
		return line_items
	
	def __str__(self):
		return f"GRN Entry for '{self.purchase_order_line_item.product_name}'"


class Conversion(models.Model):
	'''
		Defines how a product can be converted to another unit of measurement.
	'''
	name = models.CharField(max_length=100, blank=False, null=False, unique=True) # The name of the conversion.
	conversion_field = models.JSONField(default=dict, blank=False) # The fields that define the conversion.
	conversion_method = models.CharField(max_length=100, choices=get_conversion_methods()) #
	created_on = models.DateTimeField(auto_now_add=True)
	
	def __str__(self):
		return f"{self.name}"
	

class ProductConversion(models.Model):
	'''
		Associates a product with a conversion.
	'''
	product_id = models.CharField(max_length=32, blank=False, null=False, unique=True) # The ByD Product ID
	conversion = models.ForeignKey(Conversion, on_delete=models.CASCADE, related_name='product_conversion')
	created_on = models.DateTimeField(auto_now_add=True)
	
	def __str__(self):
		return f"{self.conversion.name} for '{self.product_id}'"