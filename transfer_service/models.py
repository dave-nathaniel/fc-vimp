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


class SalesOrder(models.Model):
    """
    Represents a sales order from SAP ByD for store-to-store transfers
    """
    DELIVERY_STATUS_CHOICES = [
        ('1', 'Not Started'),
        ('2', 'Partially Delivered'), 
        ('3', 'Completely Delivered')
    ]
    
    object_id = models.CharField(max_length=32, unique=True)
    sales_order_id = models.IntegerField(unique=True)
    source_store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='outbound_orders')
    destination_store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='inbound_orders')
    total_net_amount = models.DecimalField(max_digits=15, decimal_places=3)
    order_date = models.DateField()
    delivery_status_code = models.CharField(max_length=1, choices=DELIVERY_STATUS_CHOICES, default='1')
    metadata = models.JSONField(default=dict)
    created_date = models.DateTimeField(auto_now_add=True)
    
    @property
    def delivery_status(self):
        """
        Calculate delivery status based on line items
        """
        line_items = self.line_items.all()
        if not line_items:
            return self.DELIVERY_STATUS_CHOICES[0]
            
        # Check delivery status of all line items
        not_started = all(item.issued_quantity == 0 for item in line_items)
        completely_delivered = all(item.received_quantity >= item.quantity for item in line_items)
        
        if completely_delivered:
            return self.DELIVERY_STATUS_CHOICES[2]
        elif not not_started:
            return self.DELIVERY_STATUS_CHOICES[1]
        else:
            return self.DELIVERY_STATUS_CHOICES[0]
    
    @property
    def issued_quantity(self):
        """
        Total quantity issued across all line items
        """
        return sum(item.issued_quantity for item in self.line_items.all())
    
    @property
    def received_quantity(self):
        """
        Total quantity received across all line items
        """
        return sum(item.received_quantity for item in self.line_items.all())
    
    @classmethod
    def create_sales_order(cls, so_data):
        """
        Create a sales order from SAP ByD data
        """
        # Validate required fields
        required_fields = ["ObjectID", "ID"]
        for field in required_fields:
            if field not in so_data:
                raise ValidationError(f"Required field '{field}' missing from sales order data")
        
        # Use TotalNetAmount if present, else fallback to NetAmount
        total_net_amount = so_data.get("TotalNetAmount") or so_data.get("NetAmount")
        if total_net_amount is None:
            raise ValidationError("Required field 'TotalNetAmount' or 'NetAmount' missing from sales order data")
        
        # Create new sales order instance
        sales_order = cls()
        sales_order.object_id = so_data["ObjectID"]
        sales_order.sales_order_id = int(so_data["ID"])
        sales_order.total_net_amount = float(total_net_amount)
        
        # Handle date conversion
        if "LastChangeDateTime" in so_data:
            sales_order.order_date = to_python_time(so_data["LastChangeDateTime"])
        elif "CreationDateTime" in so_data:
            sales_order.order_date = to_python_time(so_data["CreationDateTime"])
        else:
            sales_order.order_date = timezone.now().date()
        
        # Get source and destination stores from SAP ByD data
        # Map SalesUnitParty to source store and BuyerParty to destination store
        sales_unit_party = so_data.get("SalesUnitParty", {})
        buyer_party = so_data.get("BuyerParty", {})
        
        source_store_code = sales_unit_party.get("PartyID") if sales_unit_party else None
        dest_store_code = buyer_party.get("PartyID") if buyer_party else None
        
        if not source_store_code or not dest_store_code:
            raise ValidationError("Source and destination store information missing from sales order")
        
        try:
            # Try to find stores by various identifiers
            sales_order.source_store = cls._find_store_by_identifier(source_store_code)
            sales_order.destination_store = cls._find_store_by_identifier(dest_store_code)
        except Store.DoesNotExist:
            raise ValidationError(f"Store not found for codes: {source_store_code}, {dest_store_code}")
        
        # Validate that source and destination are different
        if sales_order.source_store == sales_order.destination_store:
            raise ValidationError("Source and destination stores cannot be the same")
        
        # Set delivery status from SAP ByD data
        delivery_status = so_data.get("DeliveryStatusCode", "1")
        if delivery_status in [choice[0] for choice in cls.DELIVERY_STATUS_CHOICES]:
            sales_order.delivery_status_code = delivery_status
        
        # Store metadata (excluding items which will be processed separately)
        so_items = so_data.pop("Item", [])
        sales_order.metadata = so_data
        sales_order.save()
        
        # Create line items
        created = 0
        try:
            for line_item in so_items:
                sales_order.__create_line_items__(line_item)
                created += 1
        except Exception as e:
            sales_order.delete()
            raise Exception(f"Error creating line items for sales order: {e}")
            
        if created == 0:
            sales_order.delete()
            raise Exception("No line items were created for sales order.")
            
        return sales_order
    
    @staticmethod
    def _find_store_by_identifier(identifier):
        """
        Find a store by various possible identifiers
        """
        # Try different store identifier fields
        try:
            return Store.objects.get(byd_cost_center_code=identifier)
        except Store.DoesNotExist:
            try:
                return Store.objects.get(icg_warehouse_code=identifier)
            except Store.DoesNotExist:
                try:
                    # Only try ID lookup if identifier is numeric
                    if identifier.isdigit():
                        return Store.objects.get(id=int(identifier))
                    else:
                        raise Store.DoesNotExist()
                except (Store.DoesNotExist, ValueError):
                    raise Store.DoesNotExist(f"Store not found for identifier: {identifier}")
    
    def __create_line_items__(self, line_item):
        """
        Create sales order line items
        """
        so_line_item = SalesOrderLineItem()
        so_line_item.sales_order = self
        so_line_item.object_id = line_item["ObjectID"]
        so_line_item.product_name = line_item["Description"]
        # Extract ProductID from ItemProduct if present
        item_product = line_item.get("ItemProduct", {})
        so_line_item.product_id = item_product.get("ProductID") if item_product else line_item.get("ProductID")
        so_line_item.quantity = float(line_item["Quantity"])
        # Use NetAmount as unit_price if ListUnitPriceAmount is missing
        unit_price = line_item.get("ListUnitPriceAmount")
        if unit_price is None:
            # Fallback: try NetAmount/Quantity if NetAmount is present
            net_amount = line_item.get("NetAmount")
            if net_amount is not None and float(line_item["Quantity"]) != 0:
                unit_price = float(net_amount) / float(line_item["Quantity"])
            else:
                unit_price = 0.0
        so_line_item.unit_price = float(unit_price)
        so_line_item.unit_of_measurement = line_item.get("QuantityUnitCodeText", "")
        so_line_item.metadata = line_item
        so_line_item.save()
    
    def __str__(self):
        return f"SO-{self.sales_order_id}"
    
    class Meta:
        verbose_name = "Sales Order"
        verbose_name_plural = "Sales Orders"


class SalesOrderLineItem(models.Model):
    """
    Individual line items for sales orders
    """
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='line_items')
    object_id = models.CharField(max_length=32, unique=True)
    product_id = models.CharField(max_length=32)
    product_name = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=15, decimal_places=3)
    unit_price = models.DecimalField(max_digits=15, decimal_places=3)
    unit_of_measurement = models.CharField(max_length=32)
    metadata = models.JSONField(default=dict)
    
    @property
    def issued_quantity(self):
        """
        Total quantity issued for this line item
        """
        issued = self.goods_issue_items.aggregate(total_issued=Sum('quantity_issued'))['total_issued']
        return issued or 0.0
    
    @property
    def received_quantity(self):
        """
        Total quantity received for this line item
        """
        # Get received quantity through goods issue line items -> transfer receipt line items
        received = 0.0
        for gi_item in self.goods_issue_items.all():
            for tr_item in gi_item.transfer_receipt_items.all():
                received += float(tr_item.quantity_received)
        return received
    
    @property
    def delivery_status(self):
        """
        Delivery status for this specific line item
        """
        if self.received_quantity == 0:
            return self.sales_order.DELIVERY_STATUS_CHOICES[0]
        elif self.received_quantity < self.quantity:
            return self.sales_order.DELIVERY_STATUS_CHOICES[1]
        else:
            return self.sales_order.DELIVERY_STATUS_CHOICES[2]
    
    def __str__(self):
        return f"SO-{self.sales_order.sales_order_id}: {self.product_name} ({self.quantity})"
    
    class Meta:
        verbose_name = "Sales Order Line Item"
        verbose_name_plural = "Sales Order Line Items"


class GoodsIssueNote(models.Model):
    """
    Records goods dispatched from source store
    """
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='goods_issues')
    issue_number = models.IntegerField(unique=True)
    source_store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='goods_issued')
    created_date = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    posted_to_icg = models.BooleanField(default=False)
    posted_to_sap = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)
    
    @property
    def total_quantity_issued(self):
        """
        Total quantity issued in this goods issue note
        """
        return sum(float(item.quantity_issued) for item in self.line_items.all())
    
    @property
    def total_value_issued(self):
        """
        Total value of goods issued
        """
        return sum(item.value_issued for item in self.line_items.all())
    
    def save(self, *args, **kwargs):
        """
        Generate unique issue number and create line items
        """
        issue_data = kwargs.pop('issue_data', None)
        
        if not self.issue_number:
            # Generate issue number similar to GRN pattern
            base_number = int(str(self.sales_order.sales_order_id) + '1')
            self.issue_number = base_number
            
            # Ensure uniqueness
            saved = False
            while not saved:
                try:
                    super().save(*args, **kwargs)
                    saved = True
                except IntegrityError:
                    self.issue_number += 1
        else:
            super().save(*args, **kwargs)
        
        # Create line items if data provided
        if issue_data and issue_data.get('line_items'):
            try:
                self.__create_line_items__(issue_data['line_items'])
            except Exception as e:
                self.delete()
                raise e
        
        return self
    
    def __create_line_items__(self, line_items):
        """
        Create goods issue line items
        """
        for item_data in line_items:
            gi_line_item = GoodsIssueLineItem()
            gi_line_item.goods_issue = self
            gi_line_item.sales_order_line_item = SalesOrderLineItem.objects.get(
                object_id=item_data['sales_order_line_item_id']
            )
            gi_line_item.quantity_issued = item_data['quantity_issued']
            gi_line_item.metadata = item_data.get('metadata', {})
            gi_line_item.save()
    
    def post_to_icg(self):
        """
        Post goods issue to ICG inventory system
        """
        # This will be implemented in the ICG integration task
        async_task('transfer_service.tasks.post_goods_issue_to_icg', self.id)
    
    def post_to_sap(self):
        """
        Post goods issue to SAP ByD
        """
        # This will be implemented in the SAP integration task
        async_task('transfer_service.tasks.post_goods_issue_to_sap', self.id)
    
    def __str__(self):
        return f"GI-{self.issue_number}"
    
    class Meta:
        verbose_name = "Goods Issue Note"
        verbose_name_plural = "Goods Issue Notes"


class GoodsIssueLineItem(models.Model):
    """
    Individual items in a goods issue note
    """
    goods_issue = models.ForeignKey(GoodsIssueNote, on_delete=models.CASCADE, related_name='line_items')
    sales_order_line_item = models.ForeignKey(SalesOrderLineItem, on_delete=models.CASCADE, related_name='goods_issue_items')
    quantity_issued = models.DecimalField(max_digits=15, decimal_places=3)
    metadata = models.JSONField(default=dict)
    
    @property
    def value_issued(self):
        """
        Calculate value of issued goods
        """
        return float(self.quantity_issued) * float(self.sales_order_line_item.unit_price)
    
    @property
    def product_name(self):
        return self.sales_order_line_item.product_name
    
    @property
    def product_id(self):
        return self.sales_order_line_item.product_id
    
    def clean(self):
        """
        Validate quantity issued doesn't exceed available quantity
        """
        # Get total already issued for this sales order line item
        existing_issued = self.sales_order_line_item.goods_issue_items.exclude(
            id=self.id
        ).aggregate(total=Sum('quantity_issued'))['total'] or 0
        
        total_to_issue = float(existing_issued) + float(self.quantity_issued)
        
        if total_to_issue > float(self.sales_order_line_item.quantity):
            raise ValidationError(
                f"Cannot issue {self.quantity_issued}. "
                f"Available quantity: {float(self.sales_order_line_item.quantity) - float(existing_issued)}"
            )
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"GI-{self.goods_issue.issue_number}: {self.product_name} ({self.quantity_issued})"
    
    class Meta:
        verbose_name = "Goods Issue Line Item"
        verbose_name_plural = "Goods Issue Line Items"


class TransferReceiptNote(models.Model):
    """
    Records goods received at destination store
    """
    goods_issue = models.ForeignKey(GoodsIssueNote, on_delete=models.CASCADE, related_name='receipts')
    receipt_number = models.IntegerField(unique=True)
    destination_store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='goods_received')
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
            base_number = int(str(self.goods_issue.issue_number) + '1')
            self.receipt_number = base_number
            
            # Ensure uniqueness
            saved = False
            while not saved:
                try:
                    super().save(*args, **kwargs)
                    saved = True
                except IntegrityError:
                    self.receipt_number += 1
        else:
            super().save(*args, **kwargs)
        
        # Create line items if data provided
        if receipt_data and receipt_data.get('line_items'):
            try:
                self.__create_line_items__(receipt_data['line_items'])
            except Exception as e:
                self.delete()
                raise e
        
        # Check if transfer is complete and trigger SAP completion
        if not is_new or (receipt_data and receipt_data.get('line_items')):
            # Refresh sales order to get updated delivery status
            self.goods_issue.sales_order.refresh_from_db()
            delivery_status = self.goods_issue.sales_order.delivery_status
            
            # If transfer is completely delivered, trigger SAP completion
            if delivery_status[0] == '3':  # Completely Delivered
                logger.info(f"Transfer complete for sales order {self.goods_issue.sales_order.sales_order_id}, triggering SAP completion")
                self.complete_transfer_in_sap()
            else:
                # Update status for partial delivery
                logger.info(f"Transfer partially complete for sales order {self.goods_issue.sales_order.sales_order_id}, updating status")
                async_task('transfer_service.tasks.update_sales_order_status', self.goods_issue.sales_order.id)
        
        return self
    
    def __create_line_items__(self, line_items):
        """
        Create transfer receipt line items
        """
        for item_data in line_items:
            tr_line_item = TransferReceiptLineItem()
            tr_line_item.transfer_receipt = self
            tr_line_item.goods_issue_line_item = GoodsIssueLineItem.objects.get(
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
    goods_issue_line_item = models.ForeignKey(GoodsIssueLineItem, on_delete=models.CASCADE, related_name='transfer_receipt_items')
    quantity_received = models.DecimalField(max_digits=15, decimal_places=3)
    metadata = models.JSONField(default=dict)
    
    @property
    def value_received(self):
        """
        Calculate value of received goods
        """
        return float(self.quantity_received) * float(self.goods_issue_line_item.sales_order_line_item.unit_price)
    
    @property
    def product_name(self):
        return self.goods_issue_line_item.product_name
    
    @property
    def product_id(self):
        return self.goods_issue_line_item.product_id
    
    def clean(self):
        """
        Validate quantity received doesn't exceed quantity issued
        """
        # Get total already received for this goods issue line item
        existing_received = self.goods_issue_line_item.transfer_receipt_items.exclude(
            id=self.id
        ).aggregate(total=Sum('quantity_received'))['total'] or 0
        
        total_to_receive = float(existing_received) + float(self.quantity_received)
        
        if total_to_receive > float(self.goods_issue_line_item.quantity_issued):
            raise ValidationError(
                f"Cannot receive {self.quantity_received}. "
                f"Available quantity: {float(self.goods_issue_line_item.quantity_issued) - float(existing_received)}"
            )
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"TR-{self.transfer_receipt.receipt_number}: {self.product_name} ({self.quantity_received})"
    
    class Meta:
        verbose_name = "Transfer Receipt Line Item"
        verbose_name_plural = "Transfer Receipt Line Items"


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