import logging
import inspect
from django.db import models
from django.db.utils import IntegrityError
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Sum
from django.forms.models import model_to_dict
from django_q.tasks import async_task
from core_service.models import CustomUser
from egrn_service.models import Store
from byd_service.rest import RESTServices
from byd_service.util import to_python_time

# Initialize REST services
byd_rest_services = RESTServices()

# Delivery status choices for sales orders
DELIVERY_STATUS_CHOICES = [
    ('1', 'Not Delivered'),
    ('2', 'Partially Delivered'), 
    ('3', 'Completely Delivered')
]

# Store role choices for authorization
STORE_ROLE_CHOICES = [
    ('manager', 'Store Manager'),
    ('assistant', 'Store Assistant'),
    ('admin', 'Administrator'),
]


class SalesOrder(models.Model):
    """
    Represents a sales order for store-to-store transfers from SAP ByD
    """
    object_id = models.CharField(max_length=32, unique=True)
    sales_order_id = models.IntegerField(unique=True)
    source_store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='outbound_orders')
    destination_store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='inbound_orders')
    total_net_amount = models.DecimalField(max_digits=15, decimal_places=3)
    order_date = models.DateField()
    delivery_status_code = models.CharField(max_length=1, choices=DELIVERY_STATUS_CHOICES, default='1')
    metadata = models.JSONField(default=dict)
    
    @property
    def delivery_status(self):
        """Calculate delivery status based on line items"""
        status = DELIVERY_STATUS_CHOICES[0]
        order_items = self.line_items.all()
        
        # Check delivery status of all line items
        partially_delivered = [item.delivery_status[0] == '2' for item in order_items]
        completely_delivered = [item.delivery_status[0] == '3' for item in order_items]
        
        if all(completely_delivered):
            status = DELIVERY_STATUS_CHOICES[2]
        elif any(partially_delivered) or any(completely_delivered):
            status = DELIVERY_STATUS_CHOICES[1]
            
        return status
    
    def create_sales_order(self, so_data):
        """Create a sales order from SAP ByD data"""
        # Set sales order fields
        self.object_id = so_data["ObjectID"]
        self.sales_order_id = so_data["ID"]
        self.total_net_amount = so_data["TotalNetAmount"]
        self.order_date = to_python_time(so_data["LastChangeDateTime"])
        
        # Set source and destination stores based on metadata
        self.source_store = self._get_store_by_id(so_data["SourceStoreID"])
        self.destination_store = self._get_store_by_id(so_data["DestinationStoreID"])
        
        # Store metadata
        so_items = so_data.pop("Item", [])
        self.metadata = so_data
        self.save()
        
        # Create line items
        created = 0
        try:
            for line_item in so_items:
                self._create_line_items(line_item)
                created += 1
        except Exception as e:
            self.delete()
            raise Exception(f"Error creating line items for sales order: {e}")
        
        if created == 0:
            self.delete()
            raise Exception("No line items were created for sales order.")
        
        return self
    
    def _get_store_by_id(self, store_id):
        """Get store by ByD cost center code or create if not exists"""
        try:
            return Store.objects.get(byd_cost_center_code=store_id)
        except ObjectDoesNotExist:
            # You could implement store creation logic here if needed
            raise Store.DoesNotExist(f"Store with ID {store_id} not found.")
    
    def _create_line_items(self, line_item):
        """Create sales order line items"""
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
        verbose_name_plural = "Sales Orders"


class SalesOrderLineItem(models.Model):
    """
    Individual line items within a sales order
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
    def delivery_status(self):
        """Calculate delivery status based on issued/received quantities"""
        if self.issued_quantity == 0:
            return DELIVERY_STATUS_CHOICES[0]
        elif (self.issued_quantity > 0) and (self.issued_quantity < self.quantity):
            return DELIVERY_STATUS_CHOICES[1]
        elif self.issued_quantity == self.quantity:
            return DELIVERY_STATUS_CHOICES[2]
    
    @property
    def issued_quantity(self):
        """Calculate total issued quantity for this line item"""
        issued_quantity = self.goods_issue_items.aggregate(
            total_issued=Sum('quantity_issued')
        )['total_issued']
        return issued_quantity or 0.0
    
    @property
    def received_quantity(self):
        """Calculate total received quantity for this line item"""
        received_quantity = 0.0
        for issue_item in self.goods_issue_items.all():
            for receipt_item in issue_item.receipt_items.all():
                received_quantity += receipt_item.quantity_received
        return received_quantity
    
    def __str__(self):
        return f"SO-{self.sales_order.sales_order_id}: {self.product_name} ({self.quantity})"
    
    class Meta:
        verbose_name_plural = "Sales Order Line Items"


class GoodsIssueNote(models.Model):
    """
    Records goods dispatched from source stores
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
    def total_issued_value(self):
        """Calculate total value of goods issued"""
        return sum(item.issued_value for item in self.line_items.all())
    
    def save(self, *args, **kwargs):
        issue_data = kwargs.pop('issue_data', {})
        
        # Generate unique issue number
        if not self.issue_number:
            base_number = int(str(self.sales_order.sales_order_id) + '2')
            self.issue_number = base_number
            
            # Progressively increment until unique
            saved = False
            while not saved:
                try:
                    super().save(*args, **kwargs)
                    saved = True
                except IntegrityError:
                    self.issue_number += 1
                except Exception as e:
                    logging.error(e)
                    raise e
        else:
            super().save(*args, **kwargs)
        
        # Create line items if data provided
        if issue_data.get("issued_goods"):
            try:
                self._create_line_items(issue_data["issued_goods"])
            except Exception as e:
                self.delete()
                raise e
        
        # Trigger async tasks for external integrations
        if issue_data.get("issued_goods"):
            async_task('vimp.tasks.post_goods_issue_to_icg', self, q_options={
                'task_name': f'Post-Issue-{self.issue_number}-To-ICG',
            })
            async_task('vimp.tasks.post_goods_issue_to_sap', self, q_options={
                'task_name': f'Post-Issue-{self.issue_number}-To-SAP',
            })
        
        return self
    
    def _create_line_items(self, line_items):
        """Create goods issue line items"""
        created_items = {}
        for line_item in line_items:
            try:
                issue_line_item = GoodsIssueLineItem()
                issue_line_item.goods_issue = self
                issue_line_item.sales_order_line_item = SalesOrderLineItem.objects.get(
                    sales_order=self.sales_order,
                    object_id=line_item["itemObjectID"]
                )
                issue_line_item.quantity_issued = round(float(line_item.get("quantityIssued", 0)), 3)
                issue_line_item.save()
                created_items[line_item['itemObjectID']] = True
            except Exception as e:
                logging.error(f"{line_item['itemObjectID']}: {e}")
                created_items[line_item['itemObjectID']] = False
                raise e
        
        return any(created_items.values())
    
    def __str__(self):
        return f"Issue #{self.issue_number}"
    
    class Meta:
        verbose_name_plural = "Goods Issue Notes"


class GoodsIssueLineItem(models.Model):
    """
    Individual items being dispatched in a goods issue
    """
    goods_issue = models.ForeignKey(GoodsIssueNote, on_delete=models.CASCADE, related_name='line_items')
    sales_order_line_item = models.ForeignKey(SalesOrderLineItem, on_delete=models.CASCADE, related_name='goods_issue_items')
    quantity_issued = models.DecimalField(max_digits=15, decimal_places=3, default=0.000)
    metadata = models.JSONField(default=dict, blank=True, null=True)
    
    @property
    def issued_value(self):
        """Calculate value of goods issued"""
        return float(self.quantity_issued) * float(self.sales_order_line_item.unit_price)
    
    @property
    def received_quantity(self):
        """Calculate total received quantity for this issue line item"""
        received_quantity = self.receipt_items.aggregate(
            total_received=Sum('quantity_received')
        )['total_received']
        return received_quantity or 0.0
    
    def clean(self):
        """Validate goods issue line item"""
        # Check quantity is positive
        if self.quantity_issued <= 0:
            raise ValidationError("Quantity issued must be greater than 0.")
        
        # Check against available quantity
        total_issued = self.sales_order_line_item.goods_issue_items.aggregate(
            total_issued=Sum('quantity_issued')
        )['total_issued'] or 0.0
        
        outstanding_quantity = float(self.sales_order_line_item.quantity) - float(total_issued)
        
        if outstanding_quantity == 0:
            raise ValidationError("This item has been completely issued.")
        
        if float(self.quantity_issued) > outstanding_quantity:
            raise ValidationError(
                f"Quantity issued ({self.quantity_issued}) exceeds outstanding quantity ({outstanding_quantity})."
            )
    
    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Issue #{self.goods_issue.issue_number}: {self.sales_order_line_item.product_name}"
    
    class Meta:
        verbose_name_plural = "Goods Issue Line Items"


class TransferReceiptNote(models.Model):
    """
    Records goods received at destination stores
    """
    goods_issue = models.ForeignKey(GoodsIssueNote, on_delete=models.CASCADE, related_name='receipts')
    receipt_number = models.IntegerField(unique=True)
    destination_store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='goods_received')
    created_date = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    posted_to_icg = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)
    
    @property
    def total_received_value(self):
        """Calculate total value of goods received"""
        return sum(item.received_value for item in self.line_items.all())
    
    def save(self, *args, **kwargs):
        receipt_data = kwargs.pop('receipt_data', {})
        
        # Generate unique receipt number
        if not self.receipt_number:
            base_number = int(str(self.goods_issue.sales_order.sales_order_id) + '3')
            self.receipt_number = base_number
            
            # Progressively increment until unique
            saved = False
            while not saved:
                try:
                    super().save(*args, **kwargs)
                    saved = True
                except IntegrityError:
                    self.receipt_number += 1
                except Exception as e:
                    logging.error(e)
                    raise e
        else:
            super().save(*args, **kwargs)
        
        # Create line items if data provided
        if receipt_data.get("received_goods"):
            try:
                self._create_line_items(receipt_data["received_goods"])
            except Exception as e:
                self.delete()
                raise e
        
        # Trigger async tasks for external integrations
        if receipt_data.get("received_goods"):
            async_task('vimp.tasks.post_transfer_receipt_to_icg', self, q_options={
                'task_name': f'Post-Receipt-{self.receipt_number}-To-ICG',
            })
            async_task('vimp.tasks.update_sales_order_status', self, q_options={
                'task_name': f'Update-SO-{self.goods_issue.sales_order.sales_order_id}-Status',
            })
        
        return self
    
    def _create_line_items(self, line_items):
        """Create transfer receipt line items"""
        created_items = {}
        for line_item in line_items:
            try:
                receipt_line_item = TransferReceiptLineItem()
                receipt_line_item.transfer_receipt = self
                receipt_line_item.goods_issue_line_item = GoodsIssueLineItem.objects.get(
                    goods_issue=self.goods_issue,
                    sales_order_line_item__object_id=line_item["itemObjectID"]
                )
                receipt_line_item.quantity_received = round(float(line_item.get("quantityReceived", 0)), 3)
                receipt_line_item.save()
                created_items[line_item['itemObjectID']] = True
            except Exception as e:
                logging.error(f"{line_item['itemObjectID']}: {e}")
                created_items[line_item['itemObjectID']] = False
                raise e
        
        return any(created_items.values())
    
    def __str__(self):
        return f"Receipt #{self.receipt_number}"
    
    class Meta:
        verbose_name_plural = "Transfer Receipt Notes"


class TransferReceiptLineItem(models.Model):
    """
    Individual items received in a transfer receipt
    """
    transfer_receipt = models.ForeignKey(TransferReceiptNote, on_delete=models.CASCADE, related_name='line_items')
    goods_issue_line_item = models.ForeignKey(GoodsIssueLineItem, on_delete=models.CASCADE, related_name='receipt_items')
    quantity_received = models.DecimalField(max_digits=15, decimal_places=3, default=0.000)
    metadata = models.JSONField(default=dict, blank=True, null=True)
    
    @property
    def received_value(self):
        """Calculate value of goods received"""
        return float(self.quantity_received) * float(self.goods_issue_line_item.sales_order_line_item.unit_price)
    
    def clean(self):
        """Validate transfer receipt line item"""
        # Check quantity is positive
        if self.quantity_received <= 0:
            raise ValidationError("Quantity received must be greater than 0.")
        
        # Check against issued quantity
        total_received = self.goods_issue_line_item.receipt_items.aggregate(
            total_received=Sum('quantity_received')
        )['total_received'] or 0.0
        
        outstanding_quantity = float(self.goods_issue_line_item.quantity_issued) - float(total_received)
        
        if outstanding_quantity == 0:
            raise ValidationError("This item has been completely received.")
        
        if float(self.quantity_received) > outstanding_quantity:
            raise ValidationError(
                f"Quantity received ({self.quantity_received}) exceeds outstanding quantity ({outstanding_quantity})."
            )
    
    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Receipt #{self.transfer_receipt.receipt_number}: {self.goods_issue_line_item.sales_order_line_item.product_name}"
    
    class Meta:
        verbose_name_plural = "Transfer Receipt Line Items"


class StoreAuthorization(models.Model):
    """
    Links users to authorized stores with specific roles
    """
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='store_authorizations')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='authorized_users')
    role = models.CharField(max_length=50, choices=STORE_ROLE_CHOICES)
    created_date = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict)
    
    def __str__(self):
        return f"{self.user.email} - {self.store.store_name} ({self.role})"
    
    class Meta:
        unique_together = ('user', 'store')
        verbose_name_plural = "Store Authorizations"