"""
Business logic services for store-to-store transfers
"""
import logging
from django.db.models import QuerySet
from django.core.exceptions import ValidationError
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
    def validate_store_access(user: CustomUser, store_id: str) -> bool:
        """
        Validate if a user has access to a specific store
        """
        return StoreAuthorization.objects.filter(
            user=user, 
            store_id=store_id
        ).exists()
    
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
    
    def get_store_sales_orders(self, store_id: str) -> list:
        """
        Get sales orders for a specific store
        """
        try:
            return self.byd_rest.get_store_sales_orders(store_id)
        except Exception as e:
            logger.error(f"Error fetching sales orders for store {store_id}: {str(e)}")
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
    def validate_inventory_availability(store_id: str, items: list) -> bool:
        """
        Validate inventory availability at source store
        This will be implemented when ICG integration is added
        """
        # Placeholder for ICG integration
        raise NotImplementedError("ICG inventory validation not yet implemented")
    
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
        This will be implemented when SAP integration is added
        """
        # Placeholder for SAP ByD integration
        raise NotImplementedError("SAP ByD completion not yet implemented")