import logging
from django.db import models
from django.db.utils import IntegrityError
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Sum
from django_q.tasks import async_task
from django.utils import timezone

from core_service.models import CustomUser
from egrn_service.models import Store
from byd_service.rest import RESTServices
from byd_service.util import to_python_time


logger = logging.getLogger(__name__)

# Initialize REST services
byd_rest_services = RESTServices()
class InboundDelivery(models.Model):
    """
    Represents an inbound delivery notification from SAP ByD for warehouse-to-store transfers
    """
    DELIVERY_STATUS_CHOICES = [
        ('1', 'Open'),
        ('2', 'In Process'),
        ('3', 'Completed'),
        ('4', 'Cancelled')
    ]
    
    object_id = models.CharField(max_length=32, unique=True)
    delivery_id = models.CharField(max_length=50, unique=True)
    source_location_id = models.CharField(max_length=50, help_text="Warehouse/Location ID from SAP ByD")
    source_location_name = models.CharField(max_length=100, blank=True, help_text="Warehouse/Location name")
    destination_store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='inbound_deliveries')
    delivery_date = models.DateField()
    delivery_status_code = models.CharField(max_length=1, choices=DELIVERY_STATUS_CHOICES, default='1')
    delivery_type_code = models.CharField(max_length=10, blank=True, help_text="SAP ByD delivery type code")
    sales_order_reference = models.CharField(max_length=50, null=True, blank=True)
    metadata = models.JSONField(default=dict)
    created_date = models.DateTimeField(auto_now_add=True)
    
    @property
    def delivery_status(self):
        """
        Get delivery status display
        """
        return dict(self.DELIVERY_STATUS_CHOICES).get(self.delivery_status_code, 'Unknown')
    
    @property
    def total_quantity_expected(self):
        """
        Calculate total quantity expected from all line items
        """
        return sum(item.quantity_expected for item in self.line_items.all())
    
    @property
    def total_quantity_received(self):
        """
        Calculate total quantity already received
        """
        return sum(item.quantity_received for item in self.line_items.all())
    
    @property
    def is_fully_received(self):
        """
        Check if delivery is fully received
        """
        total_expected = self.total_quantity_expected
        if total_expected == 0:
            return False  # Cannot be fully received if there's nothing expected
        return self.total_quantity_received >= total_expected
    
    @classmethod
    def create_from_byd_data(cls, delivery_data):
        """
        Create an inbound delivery from SAP ByD data (warehouse-to-store)
        """
        # Validate required fields
        required_fields = ["ObjectID", "ID"]
        for field in required_fields:
            if field not in delivery_data:
                raise ValidationError(f"Required field '{field}' missing from delivery data")
        
        # Create new delivery instance
        delivery = cls()
        delivery.object_id = delivery_data["ObjectID"]
        delivery.delivery_id = delivery_data["ID"]
        delivery.delivery_status_code = delivery_data.get("DeliveryProcessingStatusCode", "1")
        delivery.delivery_type_code = delivery_data.get("DeliveryTypeCode", "")
        
        # Handle date conversion - use shipping period or creation date
        if "ShippingPeriod" in delivery_data and delivery_data["ShippingPeriod"]:
            shipping_period = delivery_data["ShippingPeriod"]
            if "StartDateTime" in shipping_period:
                delivery_datetime = to_python_time(shipping_period["StartDateTime"])
                delivery.delivery_date = delivery_datetime.date() if hasattr(delivery_datetime, 'date') else delivery_datetime
            else:
                delivery.delivery_date = timezone.now().date()
        elif "CreationDateTime" in delivery_data:
            creation_datetime = to_python_time(delivery_data["CreationDateTime"])
            delivery.delivery_date = creation_datetime.date() if hasattr(creation_datetime, 'date') else creation_datetime
        else:
            delivery.delivery_date = timezone.now().date()
        
        # Extract warehouse location information (source)
        ship_from_location = delivery_data.get("ShipFromLocation", {})
        if ship_from_location:
            delivery.source_location_id = ship_from_location.get("LocationID", "")
            # You might want to add logic to get location name from a mapping or API
            delivery.source_location_name = f"Warehouse {delivery.source_location_id}"
        
        # Extract destination store information
        product_recipient_party = delivery_data.get("ProductRecipientParty", {})
        if not product_recipient_party:
            raise ValidationError("ProductRecipientParty (destination store) information missing from delivery")
        
        dest_store_code = product_recipient_party.get("PartyID")
        if not dest_store_code:
            raise ValidationError("Destination store PartyID missing from delivery")
        
        try:
            delivery.destination_store = cls._find_store_by_identifier(dest_store_code)
        except Store.DoesNotExist:
            raise ValidationError(f"Destination store not found for delivery {delivery.delivery_id}: {dest_store_code}")
        
        # Store sales order reference if available
        delivery.sales_order_reference = delivery_data.get("SalesOrderID")
        
        # Store metadata
        delivery.metadata = delivery_data
        
        try:
            delivery.save()
            
            # Create line items
            if "Item" in delivery_data:
                delivery.__create_line_items__(delivery_data["Item"])
            
            logger.info(f"Created delivery {delivery.delivery_id} from warehouse {delivery.source_location_id} to store {delivery.destination_store.store_name}")
            return delivery
            
        except IntegrityError as e:
            logger.error(f"Error creating delivery {delivery.delivery_id}: {e}")
            raise ValidationError(f"Error creating delivery: {e}")
    
    @staticmethod
    def _find_store_by_identifier(identifier):
        """
        Find store by various identifier fields
        """
        try:
            # First try by byd_cost_center_code (most common for SAP ByD)
            return Store.objects.get(byd_cost_center_code=identifier)
        except Store.DoesNotExist:
            try:
                # Try by icg_warehouse_code
                return Store.objects.get(icg_warehouse_code=identifier)
            except Store.DoesNotExist:
                try:
                    # Try by store name
                    return Store.objects.get(store_name=identifier)
                except Store.DoesNotExist:
                    try:
                        # Try by metadata fields
                        return Store.objects.get(metadata__store_code=identifier)
                    except Store.DoesNotExist:
                        raise Store.DoesNotExist(f"Store not found with identifier: {identifier}")
    
    def __create_line_items__(self, line_items_data):
        """
        Create line items for this delivery from SAP ByD outbound delivery data
        """
        for item_data in line_items_data:
            line_item = InboundDeliveryLineItem()
            line_item.delivery = self
            line_item.object_id = item_data.get("ObjectID", "")
            line_item.product_id = item_data.get("ProductID", "")
            
            # For product name, try to get from ProductDescription or construct from ProductID
            line_item.product_name = item_data.get("ProductDescription", item_data.get("ProductID", "Unknown Product"))
            
            # Extract quantity from ItemDeliveryQuantity
            item_delivery_quantity = item_data.get("ItemDeliveryQuantity", {})
            if item_delivery_quantity:
                quantity = item_delivery_quantity.get("Quantity", "0")
                unit_code = item_delivery_quantity.get("UnitCode", "")
                unit_text = item_delivery_quantity.get("UnitCodeText", unit_code)
            else:
                # Fallback to direct quantity field
                quantity = item_data.get("Quantity", "0")
                unit_code = item_data.get("QuantityUnitCode", "")
                unit_text = unit_code
            
            line_item.quantity_expected = float(quantity)
            line_item.unit_of_measurement = unit_text if unit_text else unit_code
            line_item.metadata = item_data
            line_item.save()
    
    def __str__(self):
        return f"Delivery {self.delivery_id} - Warehouse {self.source_location_id} to {self.destination_store.store_name}"
    
    class Meta:
        verbose_name = "Inbound Delivery"
        verbose_name_plural = "Inbound Deliveries"


class InboundDeliveryLineItem(models.Model):
    """
    Individual line items for inbound deliveries
    """
    delivery = models.ForeignKey(InboundDelivery, on_delete=models.CASCADE, related_name='line_items')
    object_id = models.CharField(max_length=32)
    product_id = models.CharField(max_length=32)
    product_name = models.CharField(max_length=100)
    quantity_expected = models.DecimalField(max_digits=15, decimal_places=3)
    quantity_received = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    unit_of_measurement = models.CharField(max_length=32)
    metadata = models.JSONField(default=dict)
    
    @property
    def quantity_outstanding(self):
        """
        Calculate outstanding quantity to be received
        """
        from decimal import Decimal
        return self.quantity_expected - Decimal(str(self.quantity_received))
    
    @property
    def is_fully_received(self):
        """
        Check if line item is fully received
        """
        return self.quantity_received >= self.quantity_expected
    
    def __str__(self):
        return f"{self.product_name} - {self.quantity_expected} {self.unit_of_measurement}"
    
    class Meta:
        verbose_name = "Inbound Delivery Line Item"
        verbose_name_plural = "Inbound Delivery Line Items"


class TransferReceiptNote(models.Model):
    """
    Records goods received at destination store
    """
    inbound_delivery = models.ForeignKey(InboundDelivery, on_delete=models.CASCADE, related_name='receipts')
    receipt_number = models.IntegerField(unique=True)
    notes = models.TextField(blank=True, null=True)
    created_date = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    posted_to_icg = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)
    
    @property
    def total_quantity_received(self):
        """
        Total quantity received in this transfer receipt
        """
        return sum(float(item.quantity_received) for item in self.line_items.all())
    
    @property
    def total_value_received(self):
        """
        Total value of goods received
        """
        return sum(item.value_received for item in self.line_items.all())
    
    def save(self, *args, **kwargs):
        """
        Generate unique receipt number and create line items
        """
        receipt_data = kwargs.pop('receipt_data', None)
        is_new = self.pk is None
        
        if not self.receipt_number:
            # Generate receipt number based on goods issue number
            # Count how many transfer receipt notes are there for this inbound delivery
            count = TransferReceiptNote.objects.filter(inbound_delivery=self.inbound_delivery).count()
            self.receipt_number = f"{self.inbound_delivery.delivery_id}{count + 1}"
        
        super().save(*args, **kwargs)
        
        # Check if transfer is complete and trigger SAP completion
        if not is_new or (receipt_data and receipt_data.get('line_items')):
            # Refresh sales order to get updated delivery status
            self.inbound_delivery.refresh_from_db()
            delivery_status = self.inbound_delivery.delivery_status
            
            # If transfer is completely delivered, trigger SAP completion
            if delivery_status[0] == '3':  # Completely Delivered
                logger.info(f"Transfer complete for sales order {self.inbound_delivery.delivery_id}, triggering SAP completion")
                # self.complete_transfer_in_sap()
            else:
                # Update status for partial delivery
                logger.info(f"Transfer partially complete for sales order {self.inbound_delivery.delivery_id}, updating status")
                # async_task('transfer_service.tasks.update_sales_order_status', self.inbound_delivery.delivery_id)
        
        return self
    
    def __create_line_items__(self, line_items):
        """
        Create transfer receipt line items
        """
        for item_data in line_items:
            tr_line_item = TransferReceiptLineItem()
            tr_line_item.transfer_receipt = self
            tr_line_item.inbound_delivery_line_item = InboundDeliveryLineItem.objects.get(
                id=item_data['goods_issue_line_item_id']
            )
            tr_line_item.quantity_received = item_data['quantity_received']
            tr_line_item.metadata = item_data.get('metadata', {})
            tr_line_item.save()
    
    def update_destination_inventory(self):
        """
        Update ICG inventory at destination store
        """
        async_task('transfer_service.tasks.update_transfer_receipt_inventory', self.id)
    
    def complete_transfer_in_sap(self):
        """
        Mark transfer as completed in SAP ByD
        """
        async_task('transfer_service.tasks.complete_transfer_in_sap', self.id)
    
    def __str__(self):
        return f"TR-{self.receipt_number}"
    
    class Meta:
        verbose_name = "Transfer Receipt Note"
        verbose_name_plural = "Transfer Receipt Notes"


class TransferReceiptLineItem(models.Model):
    """
    Individual items in a transfer receipt note
    """
    transfer_receipt = models.ForeignKey(TransferReceiptNote, on_delete=models.CASCADE, related_name='line_items')
    inbound_delivery_line_item = models.ForeignKey(InboundDeliveryLineItem, on_delete=models.CASCADE, related_name='transfer_receipt_items')
    quantity_received = models.DecimalField(max_digits=15, decimal_places=3)
    metadata = models.JSONField(default=dict)
    
    @property
    def value_received(self):
        """
        Calculate value of received goods
        """
        # return float(self.quantity_received) * float(self.inbound_delivery_line_item.sales_order_line_item.unit_price)
        return 0
    
    @property
    def product_name(self):
        return self.inbound_delivery_line_item.product_id
    
    @property
    def product_id(self):
        return self.inbound_delivery_line_item.product_id
    
    def clean(self):
        """
        Validate quantity received doesn't exceed quantity issued
        """
        # Get total already received for this goods issue line item
        existing_received = self.inbound_delivery_line_item.transfer_receipt_items.exclude(
            id=self.id
        ).aggregate(total=Sum('quantity_received'))['total'] or 0
        
        total_to_receive = float(existing_received) + float(self.quantity_received)
        
        if total_to_receive > float(self.inbound_delivery_line_item.quantity_expected):
            raise ValidationError(
                f"Cannot receive {self.quantity_received}. "
                f"Available quantity: {float(self.inbound_delivery_line_item.quantity_expected) - float(existing_received)}"
            )
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"TR-{self.transfer_receipt.receipt_number}: {self.product_name} ({self.quantity_received})"
    
    class Meta:
        verbose_name = "Transfer Receipt Line Item"
        verbose_name_plural = "Transfer Receipt Line Items"



class StoreAuthorization(models.Model):
    """
    Links users to authorized stores with roles
    """
    STORE_ROLE_CHOICES = [
        ('manager', 'Store Manager'),
        ('assistant', 'Assistant Manager'),
        ('clerk', 'Store Clerk'),
        ('viewer', 'Viewer Only'),
    ]
    
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='store_authorizations')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='authorized_users')
    role = models.CharField(max_length=50, choices=STORE_ROLE_CHOICES)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'store')
        verbose_name = "Store Authorization"
        verbose_name_plural = "Store Authorizations"

    def __str__(self):
        return f"{self.user.username} - {self.store.store_name} ({self.role})"