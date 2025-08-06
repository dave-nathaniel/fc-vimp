"""
Business logic services for store-to-store transfers
"""
import logging
from django.db.models import QuerySet
from django.core.exceptions import ValidationError
from django.utils import timezone
from core_service.models import CustomUser
from egrn_service.models import Store
from .models import SalesOrder, GoodsIssueNote, TransferReceiptNote, StoreAuthorization

logger = logging.getLogger(__name__)


class AuthorizationService:
    """
    Service for managing store authorization and access control
    """
    
    @staticmethod
    def get_user_authorized_stores(user: CustomUser) -> QuerySet[Store]:
        """
        Get all stores that a user is authorized to access
        """
        return Store.objects.filter(authorized_users__user=user)
    
    @staticmethod
    def validate_store_access(user: CustomUser, byd_cost_center_code: str) -> bool:
        """
        Validate if a user has access to a specific store
        """
        store = Store.objects.get(byd_cost_center_code=byd_cost_center_code)
        return StoreAuthorization.objects.filter(
            user=user, 
            store=store
        ).exists()
    
    @staticmethod
    def validate_store_access_with_role(user: CustomUser, byd_cost_center_code: str, required_roles: list = None) -> bool:
        """
        Validate if a user has access to a specific store with required role
        """
        store = Store.objects.get(byd_cost_center_code=byd_cost_center_code)
        query = StoreAuthorization.objects.filter(user=user, store=store)
        
        if required_roles:
            query = query.filter(role__in=required_roles)
        
        return query.exists()
    
    @staticmethod
    def get_user_store_role(user: CustomUser, byd_cost_center_code: str) -> str:
        """
        Get user's role for a specific store
        """
        try:
            store = Store.objects.get(byd_cost_center_code=byd_cost_center_code)
            auth = StoreAuthorization.objects.get(user=user, store=store)
            return auth.role
        except StoreAuthorization.DoesNotExist:
            return None
    
    @staticmethod
    def validate_transfer_authorization(user: CustomUser, sales_order, operation_type: str) -> bool:
        """
        Validate user authorization for transfer operations
        """
        from .validators import StoreAuthorizationValidator
        
        if operation_type == 'goods_issue':
            # User must have access to source store
            StoreAuthorizationValidator.validate_store_access(
                user, sales_order.source_store.id, 
                required_roles=['manager', 'assistant', 'clerk']
            )
        elif operation_type == 'transfer_receipt':
            # User must have access to destination store
            StoreAuthorizationValidator.validate_store_access(
                user, sales_order.destination_store.id,
                required_roles=['manager', 'assistant', 'clerk']
            )
        elif operation_type == 'view':
            # User must have access to either source or destination store
            source_access = AuthorizationService.validate_store_access(user, sales_order.source_store.id)
            dest_access = AuthorizationService.validate_store_access(user, sales_order.destination_store.id)
            
            if not (source_access or dest_access):
                raise ValidationError(
                    f"User {user.username} is not authorized to view this transfer"
                )
        
        return True
    
    @staticmethod
    def filter_by_user_stores(queryset: QuerySet, user: CustomUser) -> QuerySet:
        """
        Filter a queryset to only include records for stores the user has access to
        """
        authorized_stores = AuthorizationService.get_user_authorized_stores(user)
        
        # Handle different model types
        if hasattr(queryset.model, 'source_store'):
            return queryset.filter(source_store__in=authorized_stores)
        elif hasattr(queryset.model, 'destination_store'):
            return queryset.filter(destination_store__in=authorized_stores)
        elif hasattr(queryset.model, 'store'):
            return queryset.filter(store__in=authorized_stores)
        
        return queryset


class SalesOrderService:
    """
    Service for managing sales orders from SAP ByD
    """
    
    def __init__(self):
        from byd_service.rest import RESTServices
        self.byd_rest = RESTServices()
    
    def fetch_sales_order_by_id(self, sales_order_id: str) -> dict:
        """
        Fetch a sales order from SAP ByD by ID
        """
        try:
            return self.byd_rest.get_sales_order_by_id(sales_order_id)
        except Exception as e:
            logger.error(f"Error fetching sales order {sales_order_id}: {str(e)}")
            raise
    
    def get_store_sales_orders(self, byd_cost_center_code: str) -> list:
        """
        Get sales orders for a specific store
        """
        try:
            return self.byd_rest.get_store_sales_orders(byd_cost_center_code)
        except Exception as e:
            logger.error(f"Error fetching sales orders for store {byd_cost_center_code}: {str(e)}")
            raise
    
    def update_sales_order_status(self, sales_order_id: str, status: str) -> bool:
        """
        Update sales order status in SAP ByD
        """
        try:
            return self.byd_rest.update_sales_order_status(sales_order_id, status)
        except Exception as e:
            logger.error(f"Error updating sales order status: {str(e)}")
            raise
    
    def create_or_update_local_sales_order(self, sales_order_id: str):
        """
        Fetch sales order from SAP ByD and create/update local record
        """
        try:
            # Check if sales order already exists locally
            try:
                local_so = SalesOrder.objects.get(sales_order_id=sales_order_id)
                logger.info(f"Sales order {sales_order_id} already exists locally")
                return local_so
            except SalesOrder.DoesNotExist:
                pass
            
            # Fetch from SAP ByD
            sap_data = self.fetch_sales_order_by_id(sales_order_id)
            if not sap_data:
                raise ValidationError(f"Sales order {sales_order_id} not found in SAP ByD")
            
            # Create local sales order
            local_so = SalesOrder.create_sales_order(sap_data)
            logger.info(f"Created local sales order {sales_order_id}")
            return local_so
            
        except Exception as e:
            logger.error(f"Error creating/updating local sales order {sales_order_id}: {str(e)}")
            raise


class GoodsIssueService:
    """
    Service for managing goods issue process
    """
    
    @staticmethod
    def create_goods_issue(issue_data: dict) -> GoodsIssueNote:
        """
        Create a goods issue note with validation
        This will be fully implemented in the goods issue creation task
        """
        # Basic validation placeholder
        if not issue_data.get('sales_order_id'):
            raise ValidationError("Sales order ID is required")
        
        # Placeholder for full implementation
        raise NotImplementedError("Goods issue creation not yet implemented")
    
    @staticmethod
    def validate_inventory_availability(byd_cost_center_code: str, items: list) -> bool:
        """
        Validate inventory availability at source store
        This is a placeholder for ICG integration
        """
        from .validators import InventoryValidator
        
        # Use the validator for basic validation
        InventoryValidator.validate_inventory_availability(byd_cost_center_code, items)
        
        # Placeholder for actual ICG inventory check
        logger.info(f"Validating inventory availability for store {byd_cost_center_code}")
        
        # In real implementation, this would:
        # 1. Call ICG API to get current inventory levels
        # 2. Check if requested quantities are available
        # 3. Return detailed availability information
        
        # For now, simulate inventory check with business rules
        for item in items:
            product_id = item.get('product_id')
            requested_quantity = float(item.get('quantity', 0))
            
            # Simulate inventory check (placeholder logic)
            # In real implementation, this would be an ICG API call
            simulated_available = 100.0  # Placeholder available quantity
            
            if requested_quantity > simulated_available:
                raise ValidationError(
                    f"Insufficient inventory for product {product_id}. "
                    f"Requested: {requested_quantity}, Available: {simulated_available}"
                )
            
            logger.info(f"Inventory check passed for product {product_id}: {requested_quantity}/{simulated_available}")
        
        return True
    
    @staticmethod
    def validate_goods_issue_business_rules(sales_order, line_items_data, user, source_store):
        """
        Validate all business rules for goods issue creation
        """
        from .validators import (
            BusinessRuleValidator, 
            StoreAuthorizationValidator,
            GoodsIssueValidator
        )
        
        # Validate sales order status
        BusinessRuleValidator.validate_sales_order_status_for_operation(
            sales_order, 'goods_issue'
        )
        
        # Validate store authorization
        StoreAuthorizationValidator.validate_store_access(
            user, source_store.id, required_roles=['manager', 'assistant', 'clerk']
        )
        
        # Validate store relationships
        BusinessRuleValidator.validate_store_relationship_constraints(
            sales_order, source_store=source_store
        )
        
        # Validate line item relationships
        BusinessRuleValidator.validate_line_item_relationships(
            line_items_data, sales_order, 'goods_issue'
        )
        
        # Validate quantity constraints
        BusinessRuleValidator.validate_quantity_constraints(
            line_items_data, 'goods_issue'
        )
        
        # Validate goods issue specific rules
        GoodsIssueValidator.validate_goods_issue_creation(
            sales_order, source_store, line_items_data, user
        )
        
        # Validate inventory availability (placeholder)
        inventory_items = [
            {
                'product_id': item['sales_order_line_item'].product_id,
                'quantity': item['quantity_issued']
            }
            for item in line_items_data
        ]
        GoodsIssueService.validate_inventory_availability(source_store.id, inventory_items)
        
        return True
    
    @staticmethod
    def post_to_icg_inventory(goods_issue: GoodsIssueNote) -> bool:
        """
        Post goods issue to ICG inventory system
        This will be implemented when ICG integration is added
        """
        # Placeholder for ICG integration
        raise NotImplementedError("ICG inventory posting not yet implemented")
    
    @staticmethod
    def post_to_sap_byd(goods_issue: GoodsIssueNote) -> bool:
        """
        Post goods issue to SAP ByD
        This will be implemented when SAP integration is added
        """
        # Placeholder for SAP ByD integration
        raise NotImplementedError("SAP ByD posting not yet implemented")


class DeliveryService:
    """
    Service for managing inbound delivery operations
    """
    
    def __init__(self):
        from byd_service.rest import RESTServices
        self.byd_rest = RESTServices()
    
    def search_deliveries_by_id(self, delivery_id: str, user_byd_cost_center_codes: list) -> dict:
        """
        Search for deliveries by ID across local database and SAP ByD
        """
        from .models import InboundDelivery
        
        results = {
            'local': [],
            'sap_byd': []
        }
        
        # Search local database first
        local_deliveries = InboundDelivery.objects.filter(
            delivery_id__icontains=delivery_id,
            destination_store__byd_cost_center_code__in=user_byd_cost_center_codes
        )
        
        for delivery in local_deliveries:
            results['local'].append(delivery)
        
        # If no local results, search SAP ByD
        if not results['local']:
            for byd_cost_center_code in user_byd_cost_center_codes:
                try:
                    byd_deliveries = self.byd_rest.search_deliveries_by_store(byd_cost_center_code)
                    matching_deliveries = [
                        d for d in byd_deliveries 
                        if delivery_id.lower() in d.get('ID', '').lower()
                    ]
                    results['sap_byd'].extend(matching_deliveries)
                except Exception as e:
                    logger.warning(f"Error searching SAP ByD for store {byd_cost_center_code}: {e}")
                    continue
        
        return results
    
    def fetch_and_create_delivery(self, delivery_id: str):
        """
        Fetch delivery from SAP ByD and create local record
        """
        from .models import InboundDelivery
        
        try:
            delivery_data = self.byd_rest.get_delivery_by_id(delivery_id)
            if not delivery_data:
                raise ValidationError(f"Delivery {delivery_id} not found in SAP ByD")
            
            return InboundDelivery.create_from_byd_data(delivery_data)
        except Exception as e:
            logger.error(f"Error fetching delivery {delivery_id}: {e}")
            raise
    
    def validate_delivery_receipt(self, delivery, line_items_data, user):
        """
        Validate delivery receipt creation
        """
        # Check delivery status
        if delivery.delivery_status_code not in ['1', '2']:
            raise ValidationError(f"Cannot receive from delivery in status: {delivery.delivery_status}")
        
        # Check user authorization
        if not AuthorizationService.validate_store_access(user, delivery.destination_store.byd_cost_center_code):
            raise ValidationError("User not authorized for this delivery's destination store")
        
        # Validate line items
        for item_data in line_items_data:
            delivery_line_item = item_data.get('delivery_line_item')
            quantity_received = item_data.get('quantity_received', 0)
            
            if not delivery_line_item or delivery_line_item.delivery != delivery:
                raise ValidationError("Invalid delivery line item")
            
            if quantity_received <= 0:
                raise ValidationError("Quantity received must be greater than 0")
            
            # Check if receiving would exceed expected quantity
            total_received = delivery_line_item.quantity_received + quantity_received
            if total_received > delivery_line_item.quantity_expected:
                raise ValidationError(
                    f"Total received quantity ({total_received}) would exceed expected quantity ({delivery_line_item.quantity_expected}) for product {delivery_line_item.product_name}"
                )


class TransferReceiptService:
    """
    Service for managing transfer receipt process
    """
    
    @staticmethod
    def create_transfer_receipt(receipt_data: dict) -> TransferReceiptNote:
        """
        Create a transfer receipt note with validation
        This will be fully implemented in the transfer receipt creation task
        """
        # Basic validation placeholder
        if not receipt_data.get('goods_issue_id'):
            raise ValidationError("Goods issue ID is required")
        
        # Placeholder for full implementation
        raise NotImplementedError("Transfer receipt creation not yet implemented")
    
    @staticmethod
    def validate_against_goods_issue(receipt: TransferReceiptNote) -> bool:
        """
        Validate transfer receipt against corresponding goods issue
        This will be implemented in the transfer receipt validation task
        """
        # Placeholder for validation logic
        raise NotImplementedError("Transfer receipt validation not yet implemented")
    
    @staticmethod
    def validate_transfer_receipt_business_rules(goods_issue, line_items_data, user, destination_store):
        """
        Validate all business rules for transfer receipt creation
        """
        from .validators import (
            BusinessRuleValidator,
            StoreAuthorizationValidator,
            TransferReceiptValidator
        )
        
        # Validate transfer completion rules
        BusinessRuleValidator.validate_transfer_completion_rules(goods_issue)
        
        # Validate sales order status
        BusinessRuleValidator.validate_sales_order_status_for_operation(
            goods_issue.sales_order, 'transfer_receipt'
        )
        
        # Validate store authorization
        StoreAuthorizationValidator.validate_store_access(
            user, destination_store.id, required_roles=['manager', 'assistant', 'clerk']
        )
        
        # Validate store relationships
        BusinessRuleValidator.validate_store_relationship_constraints(
            goods_issue.sales_order, destination_store=destination_store
        )
        
        # Validate line item relationships
        BusinessRuleValidator.validate_line_item_relationships(
            line_items_data, goods_issue, 'transfer_receipt'
        )
        
        # Validate quantity constraints
        BusinessRuleValidator.validate_quantity_constraints(
            line_items_data, 'transfer_receipt'
        )
        
        # Validate transfer receipt specific rules
        TransferReceiptValidator.validate_transfer_receipt_creation(
            goods_issue, destination_store, line_items_data, user
        )
        
        return True
    
    @staticmethod
    def validate_receipt_quantities(goods_issue, line_items_data):
        """
        Validate receipt quantities against issued quantities
        """
        errors = []
        
        for i, item_data in enumerate(line_items_data):
            line_number = i + 1
            gi_line_item = item_data.get('goods_issue_line_item')
            quantity_received = item_data.get('quantity_received', 0)
            
            if not gi_line_item:
                errors.append(f"Line item {line_number}: Goods issue line item is required")
                continue
            
            # Validate line item belongs to goods issue
            if gi_line_item.goods_issue != goods_issue:
                errors.append(
                    f"Line item {line_number}: Line item does not belong to the specified goods issue"
                )
                continue
            
            # Check existing received quantities
            from django.db.models import Sum
            existing_received = gi_line_item.transfer_receipt_items.aggregate(
                total=Sum('quantity_received')
            )['total'] or 0
            
            available_quantity = float(gi_line_item.quantity_issued) - float(existing_received)
            
            if float(quantity_received) > available_quantity:
                errors.append(
                    f"Line item {line_number}: Cannot receive {quantity_received}. "
                    f"Available quantity: {available_quantity}"
                )
        
        if errors:
            raise ValidationError(errors)
        
        return True
    
    @staticmethod
    def check_quantity_variations(line_items_data):
        """
        Check for quantity variations between issued and received quantities
        """
        variations = []
        
        for item_data in line_items_data:
            gi_line_item = item_data.get('goods_issue_line_item')
            quantity_received = float(item_data.get('quantity_received', 0))
            
            if gi_line_item:
                quantity_issued = float(gi_line_item.quantity_issued)
                
                if quantity_received != quantity_issued:
                    variations.append({
                        'product_id': gi_line_item.product_id,
                        'product_name': gi_line_item.product_name,
                        'quantity_issued': quantity_issued,
                        'quantity_received': quantity_received,
                        'variance': quantity_received - quantity_issued
                    })
        
        return variations
    
    @staticmethod
    def update_destination_inventory(receipt: TransferReceiptNote) -> bool:
        """
        Update ICG inventory at destination store
        This will be implemented when ICG integration is added
        """
        # Placeholder for ICG integration
        raise NotImplementedError("ICG inventory update not yet implemented")
    
    @staticmethod
    def complete_transfer_in_sap(receipt: TransferReceiptNote) -> bool:
        """
        Mark transfer as completed in SAP ByD
        """
        from byd_service.rest import RESTServices
        
        try:
            byd_service = RESTServices()
            sales_order = receipt.goods_issue.sales_order
            
            # Get goods issue SAP object ID from metadata if available
            goods_issue_object_id = receipt.goods_issue.metadata.get('sap_object_id')
            
            # Complete the transfer in SAP ByD
            result = byd_service.complete_transfer_in_sap(
                str(sales_order.sales_order_id),
                goods_issue_object_id
            )
            
            if result.get('success'):
                # Update local sales order status
                sales_order.delivery_status_code = '3'  # Completely Delivered
                sales_order.metadata.update({
                    'transfer_completed_date': timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'sap_completion_response': result,
                    'goods_issue_linked': goods_issue_object_id is not None
                })
                sales_order.save()
                
                logger.info(f"Transfer completed in SAP ByD for sales order {sales_order.sales_order_id}")
                return True
            else:
                logger.error(f"Failed to complete transfer in SAP ByD for sales order {sales_order.sales_order_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error completing transfer in SAP ByD: {str(e)}")
            return False