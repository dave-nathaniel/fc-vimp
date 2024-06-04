import logging
import inspect
from . import converters
from django.db import models
from django.db.utils import IntegrityError
from core_service.models import VendorProfile
from byd_service.rest import RESTServices
from byd_service.util import to_python_time
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum

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
		try:
			# Get the receipt fields for the product if any are defined
			receipt_fields = ProductReceiptFields.objects.get(product_id=line_item["ProductID"])
		except ObjectDoesNotExist:
			receipt_fields = None
		
		po_line_item.purchase_order = self
		po_line_item.object_id = line_item["ObjectID"]
		po_line_item.product_name = line_item["Description"]
		po_line_item.quantity = float(line_item["Quantity"])
		po_line_item.unit_price = line_item["ListUnitPriceAmount"]
		po_line_item.unit_of_measurement = line_item["QuantityUnitCodeText"]
		po_line_item.extra_fields = receipt_fields.extra_fields if receipt_fields else []
		po_line_item.metadata = line_item
		
		po_line_item.save()
	
	def __str__(self):
		return f"PO-{self.po_id}"


class PurchaseOrderLineItem(models.Model):
	purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='line_items')
	object_id = models.CharField(max_length=32, blank=False, null=False, unique=True)
	product_name = models.CharField(max_length=100)
	quantity = models.DecimalField(max_digits=15, decimal_places=3)
	unit_price = models.DecimalField(max_digits=15, decimal_places=3)
	unit_of_measurement = models.CharField(max_length=32, blank=False, null=False)
	# extra_fields = models.JSONField(default=list, null=True, blank=True)
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
				grn_line_item.extra_fields = line_item.get("extra_fields", {})
				grn_line_item.save(
					quantity_received=float(line_item["quantityReceived"]),
				)
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
	metadata = models.JSONField(default=dict)
	date_received = models.DateField(auto_now=True)
	
	@property
	def value_received(self):
		return self.quantity_received * self.purchase_order_line_item.unit_price
	
	def save(self, *args, **kwargs):
		"""
			Saves the instance to the database.
		"""
		# Get the sum of the quantity received for this item by adding up the quantity received
		# of all GRN line items for this particular PO line item.
		grns_raised_for_this = self.get_grn_for_po_line(self.purchase_order_line_item.object_id)
		total_received = grns_raised_for_this.aggregate(total_sum=Sum('quantity_received'))['total_sum']
		total_received = total_received or 0.00
		# Get the quantity that is being received for this item.
		quantity_to_receive = kwargs.pop("quantity_received")
		# Get the sum of the quantity received and the total quantity received for this item.
		sum_quantity = float(quantity_to_receive) + float(total_received)
		# Get the outstanding delivery for this item.
		outstanding_quantity = float(self.purchase_order_line_item.quantity) - float(total_received)
		# Check to see if there is any outstanding delivery for this item.
		if outstanding_quantity == 0:
			raise ValueError("This item has been completely delivered.")
		# Check to see if the quantity received is greater than the outstanding quantity.
		if sum_quantity > self.purchase_order_line_item.quantity:
			raise ValueError(
				f"Quantity received ({quantity_to_receive}) is greater than outstanding delivery quantity ({outstanding_quantity}).")
		
		# Set the quantity received for this line item to the quantity received.
		self.quantity_received = quantity_to_receive
		
		return super().save(*args, **kwargs)
	
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
	