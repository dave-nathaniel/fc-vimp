import logging
from django.db import models
from django.db.utils import IntegrityError
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Sum
from django_q.tasks import async_task

from core_service.models import CustomUser
from egrn_service.models import Store
from byd_service.rest import RESTServices
from byd_service.util import to_python_time


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
        required_fields = ["ObjectID", "ID", "TotalNetAmount"]
        for field in required_fields:
            if field not in so_data:
                raise ValidationError(f"Required field '{field}' missing from sales order data")
        
        # Create new sales order instance
        sales_order = cls()
        sales_order.object_id = so_data["ObjectID"]
        sales_order.sales_order_id = int(so_data["ID"])
        sales_order.total_net_amount = float(so_data["TotalNetAmount"])
        
        # Handle date conversion
        if "LastChangeDateTime" in so_data:
            sales_order.order_date = to_python_time(so_data["LastChangeDateTime"])
        elif "CreationDateTime" in so_data:
            sales_order.order_date = to_python_time(so_data["CreationDateTime"])
        else:
            from django.utils import timezone
            sales_order.order_date = timezone.now().date()
        
        # Get source and destination stores from SAP ByD data
        # Map SellerParty to source store and BuyerParty to destination store
        seller_party = so_data.get("SellerParty", {})
        buyer_party = so_data.get("BuyerParty", {})
        
        source_store_code = seller_party.get("PartyID") if seller_party else None
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
        so_line_item.product_id = line_item["ProductID"]
        so_line_item.quantity = float(line_item["Quantity"])
        so_line_item.unit_price = line_item["ListUnitPriceAmount"]
        so_line_item.unit_of_measurement = line_item["QuantityUnitCodeText"]
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
        async_task('transfer_service.tasks.update_sales_order_status', self.goods_issue.sales_order.id)
    
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