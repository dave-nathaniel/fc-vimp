from django.db import models
from django.db.utils import IntegrityError
from core_service.models import VendorProfile
from byd_service.rest import RESTServices
from byd_service.util import to_python_time
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum

# Initialize REST services
byd_rest_services = RESTServices()


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
	total_gross_amount = models.DecimalField(max_digits=15, decimal_places=3, blank=False, null=False)
	date = models.DateField()
	metadata = models.JSONField(default=dict)

	def create_purchase_order(self, po):
		# Get the vendor's profile (if they've completed their onboarding), or create a profile that will be attached
		# to the vendor whenever they complete their onboarding.
		supplier = po.pop("Supplier")
		vendor, created = VendorProfile.objects.get_or_create(byd_internal_id=supplier["PartyID"])
		if not created:
			vendor.byd_metadata = supplier
			vendor.save()

		self.vendor = vendor
		self.object_id = po["ObjectID"]
		self.total_net_amount = po["TotalNetAmount"]
		self.po_id = po["ID"]
		self.total_gross_amount = po["TotalGrossAmount"]
		self.date = to_python_time(po["LastChangeDateTime"])
		self.metadata = po

		po_items = po.pop("Item")
		self.save()

		for line_item in po_items:
			self.__create_line_items__(line_item)

		return self

	def __create_line_items__(self, line_item):
		po_line_item = PurchaseOrderLineItem()

		po_line_item.purchase_order = self
		po_line_item.object_id = line_item["ObjectID"]
		po_line_item.product_name = line_item["Description"]
		po_line_item.quantity = float(line_item["Quantity"])
		po_line_item.unit_price = line_item["ListUnitPriceAmount"]
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
	metadata = models.JSONField(default=dict)

	def __str__(self):
		return f"{self.product_name} ({self.quantity})"


class GoodsReceivedNote(models.Model):
	purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE)
	store = models.ForeignKey(Store, on_delete=models.CASCADE)
	grn_number = models.IntegerField(blank=False, null=False, unique=True)
	received_date = models.DateField(auto_now=True)

	def save(self, *args, **kwargs):
		grn_data = kwargs.pop('grn_data')
		po_id = grn_data['po_id']

		try:
			# Try to retrieve an object by a specific field
			purchase_order = PurchaseOrder.objects.get(po_id=po_id)
			# If the object is found, you can work with it here
		except ObjectDoesNotExist:
			po_data = byd_rest_services.get_purchase_order_by_id(po_id)
			# Create the Purchase Order
			new_po = PurchaseOrder()
			purchase_order = new_po.create_purchase_order(po_data)
		except Exception as e:
			raise e

		self.purchase_order = purchase_order
		self.store = Store.objects.all()[0]
		self.grn_number = grn_data["GRN"]
		try:
			super().save(*args, **kwargs)
			grn = self
		except IntegrityError as e:
			grn = GoodsReceivedNote.objects.get(grn_number=grn_data["GRN"])
		
		grn_line_items = grn_data["recievedGoods"]
		
		for line_item in grn_line_items:
			self.__create_line_items__(grn, line_item)
		
		return grn
	
	def __create_line_items__(self, grn, line_item):
		grn_line_item = GoodsReceivedLineItem()
		po_line_item = PurchaseOrderLineItem.objects.get(object_id=line_item["itemObjectID"])
		if po_line_item:
			grn_line_item.grn = grn
			grn_line_item.purchase_order_line_item = po_line_item
			grn_line_item.save(quantity_received=float(line_item["quantityReceived"]))

	def __str__(self):
		return f"e-GRN #{self.grn_number}"


class GoodsReceivedLineItem(models.Model):
	grn = models.ForeignKey(GoodsReceivedNote, on_delete=models.CASCADE)
	purchase_order_line_item = models.ForeignKey(PurchaseOrderLineItem, on_delete=models.CASCADE)
	quantity_received = models.DecimalField(max_digits=15, decimal_places=3, default=0.000)
	
	def save(self, *args, **kwargs):
		grns_raised_for_this = self.get_grn_for_po_line(self.purchase_order_line_item.object_id)
		total_received = grns_raised_for_this.aggregate(total_sum=Sum('quantity_received'))['total_sum']
		total_received = total_received or 0.00
		
		quantity_received = kwargs.pop("quantity_received")
		if (total_received < self.purchase_order_line_item.quantity) and (quantity_received <= self.purchase_order_line_item.quantity):
			self.quantity_received = quantity_received
			
			return super().save(*args, **kwargs)
			
		return False
	
	def get_grn_for_po_line(self, object_id):
		line_items = GoodsReceivedLineItem.objects.filter(purchase_order_line_item__object_id=object_id)
		return line_items
		
	def __str__(self):
		return f"GRN Entry for '{self.purchase_order_line_item.product_name}'"
	
