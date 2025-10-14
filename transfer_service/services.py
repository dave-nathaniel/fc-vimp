"""
Business logic services for store-to-store transfers
"""
import logging
from django.db.models import QuerySet
from django.core.exceptions import ValidationError
from django.utils import timezone
from core_service.models import CustomUser
from egrn_service.models import Store
from .models import InboundDelivery, TransferReceiptNote, StoreAuthorization

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
        if not receipt_data.get('inbound_delivery_id'):
            raise ValidationError("Goods issue ID is required")
        
        # Placeholder for full implementation
        raise NotImplementedError("Transfer receipt creation not yet implemented")
    
    @staticmethod
    def validate_against_inbound_delivery(receipt: TransferReceiptNote) -> bool:
        """
        Validate transfer receipt against corresponding goods issue
        This will be implemented in the transfer receipt validation task
        """
        # Placeholder for validation logic
        raise NotImplementedError("Transfer receipt validation not yet implemented")
        """
        Mark transfer as completed in SAP ByD
        """
        from byd_service.rest import RESTServices
        
        try:
            byd_service = RESTServices()
            sales_order = receipt.inbound_delivery.delivery_id
            
            # Get goods issue SAP object ID from metadata if available
            goods_issue_object_id = receipt.inbound_delivery.metadata.get('sap_object_id')
            
            # Complete the transfer in SAP ByD
            result = byd_service.complete_transfer_in_sap(
                str(sales_order.sales_order_id),
                inbound_delivery_object_id
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