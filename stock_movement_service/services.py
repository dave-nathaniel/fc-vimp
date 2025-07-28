import os
import logging
from typing import List, Dict, Optional
from requests import get, post
from pathlib import Path
from dotenv import load_dotenv
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet, Q
from core_service.models import CustomUser
from egrn_service.models import Store
from byd_service.rest import RESTServices
from .models import SalesOrder, StoreAuthorization

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

# Initialize REST services
byd_rest_services = RESTServices()


class SalesOrderService:
    """
    Service for managing sales orders from SAP ByD
    """
    
    def __init__(self):
        self.byd_rest = byd_rest_services
    
    def fetch_sales_order_by_id(self, sales_order_id: str) -> Optional[Dict]:
        """
        Fetch a specific sales order from SAP ByD
        """
        try:
            # This would be implemented to call SAP ByD REST API
            # For now, returning mock data for the sample sales orders
            mock_data = self._get_mock_sales_order(sales_order_id)
            return mock_data
        except Exception as e:
            logging.error(f"Error fetching sales order {sales_order_id}: {e}")
            return None
    
    def get_store_sales_orders(self, store_id: str) -> List[Dict]:
        """
        Get all sales orders for a specific store
        """
        try:
            # Mock implementation - would call SAP ByD API
            mock_orders = []
            for so_id in ['59461', '59462', '59463']:
                order_data = self._get_mock_sales_order(so_id)
                if (order_data and 
                    (order_data.get('SourceStoreID') == store_id or 
                     order_data.get('DestinationStoreID') == store_id)):
                    mock_orders.append(order_data)
            return mock_orders
        except Exception as e:
            logging.error(f"Error fetching sales orders for store {store_id}: {e}")
            return []
    
    def update_sales_order_status(self, sales_order_id: str, status: str) -> bool:
        """
        Update sales order status in SAP ByD
        """
        try:
            # Mock implementation - would call SAP ByD API
            logging.info(f"Updated sales order {sales_order_id} status to {status}")
            return True
        except Exception as e:
            logging.error(f"Error updating sales order {sales_order_id} status: {e}")
            return False
    
    def _get_mock_sales_order(self, sales_order_id: str) -> Optional[Dict]:
        """
        Mock data for testing - would be replaced with actual SAP ByD API calls
        """
        mock_orders = {
            '59461': {
                "ObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0001",
                "ID": 59461,
                "TotalNetAmount": 15000.500,
                "LastChangeDateTime": "2023-12-01T10:00:00Z",
                "SourceStoreID": "STORE001",
                "DestinationStoreID": "STORE002",
                "Item": [
                    {
                        "ObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0002",
                        "ProductID": "PROD001",
                        "Description": "Premium Coffee Beans",
                        "Quantity": "100.000",
                        "ListUnitPriceAmount": 150.00,
                        "QuantityUnitCodeText": "KG"
                    },
                    {
                        "ObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0003",
                        "ProductID": "PROD002", 
                        "Description": "Sugar Packets",
                        "Quantity": "500.000",
                        "ListUnitPriceAmount": 2.50,
                        "QuantityUnitCodeText": "PKT"
                    }
                ]
            },
            '59462': {
                "ObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0004",
                "ID": 59462,
                "TotalNetAmount": 8750.250,
                "LastChangeDateTime": "2023-12-02T14:30:00Z",
                "SourceStoreID": "STORE002",
                "DestinationStoreID": "STORE003",
                "Item": [
                    {
                        "ObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0005",
                        "ProductID": "PROD003",
                        "Description": "Milk Powder",
                        "Quantity": "50.000",
                        "ListUnitPriceAmount": 175.00,
                        "QuantityUnitCodeText": "KG"
                    }
                ]
            },
            '59463': {
                "ObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0006",
                "ID": 59463,
                "TotalNetAmount": 12300.750,
                "LastChangeDateTime": "2023-12-03T09:15:00Z",
                "SourceStoreID": "STORE001",
                "DestinationStoreID": "STORE003",
                "Item": [
                    {
                        "ObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0007",
                        "ProductID": "PROD004",
                        "Description": "Packaging Materials",
                        "Quantity": "200.000",
                        "ListUnitPriceAmount": 61.50,
                        "QuantityUnitCodeText": "PC"
                    }
                ]
            }
        }
        return mock_orders.get(sales_order_id)


class GoodsIssueService:
    """
    Service for managing goods issue process
    """
    
    def __init__(self):
        self.icg_service = ICGInventoryService()
    
    def validate_inventory_availability(self, store_id: str, items: List[Dict]) -> bool:
        """
        Validate that sufficient inventory is available at source store
        """
        try:
            # Mock validation - would check ICG inventory
            for item in items:
                product_id = item.get('product_id')
                quantity_needed = item.get('quantity', 0)
                
                # Mock check - assume inventory is available
                available_quantity = self._get_mock_inventory(store_id, product_id)
                if available_quantity < quantity_needed:
                    logging.warning(f"Insufficient inventory for {product_id} at store {store_id}")
                    return False
            
            return True
        except Exception as e:
            logging.error(f"Error validating inventory: {e}")
            return False
    
    def post_to_icg_inventory(self, goods_issue) -> bool:
        """
        Post goods issue to ICG inventory system (decrease source store inventory)
        """
        try:
            # Mock implementation - would call ICG API
            logging.info(f"Posted goods issue {goods_issue.issue_number} to ICG")
            goods_issue.posted_to_icg = True
            goods_issue.save()
            return True
        except Exception as e:
            logging.error(f"Error posting to ICG: {e}")
            return False
    
    def post_to_sap_byd(self, goods_issue) -> bool:
        """
        Post goods issue to SAP ByD system
        """
        try:
            # Mock implementation - would call SAP ByD API
            logging.info(f"Posted goods issue {goods_issue.issue_number} to SAP ByD")
            goods_issue.posted_to_sap = True
            goods_issue.save()
            return True
        except Exception as e:
            logging.error(f"Error posting to SAP ByD: {e}")
            return False
    
    def _get_mock_inventory(self, store_id: str, product_id: str) -> float:
        """Mock inventory check"""
        # Mock implementation - return sufficient inventory
        return 1000.0


class TransferReceiptService:
    """
    Service for managing transfer receipt process
    """
    
    def __init__(self):
        self.icg_service = ICGInventoryService()
        self.so_service = SalesOrderService()
    
    def validate_against_goods_issue(self, receipt) -> bool:
        """
        Validate that receipt quantities don't exceed goods issue quantities
        """
        try:
            for receipt_item in receipt.line_items.all():
                issue_item = receipt_item.goods_issue_line_item
                total_received = issue_item.received_quantity
                
                if total_received > issue_item.quantity_issued:
                    logging.warning(f"Receipt quantity exceeds issued quantity for item {issue_item.id}")
                    return False
            
            return True
        except Exception as e:
            logging.error(f"Error validating receipt: {e}")
            return False
    
    def update_destination_inventory(self, receipt) -> bool:
        """
        Update inventory at destination store (increase inventory)
        """
        try:
            # Mock implementation - would call ICG API
            logging.info(f"Updated destination inventory for receipt {receipt.receipt_number}")
            receipt.posted_to_icg = True
            receipt.save()
            return True
        except Exception as e:
            logging.error(f"Error updating destination inventory: {e}")
            return False
    
    def complete_transfer_in_sap(self, receipt) -> bool:
        """
        Complete the transfer process in SAP ByD
        """
        try:
            sales_order = receipt.goods_issue.sales_order
            return self.so_service.update_sales_order_status(
                str(sales_order.sales_order_id), 
                "COMPLETED"
            )
        except Exception as e:
            logging.error(f"Error completing transfer in SAP: {e}")
            return False


class AuthorizationService:
    """
    Service for managing store access control and user permissions
    """
    
    def get_user_authorized_stores(self, user: CustomUser) -> QuerySet[Store]:
        """
        Get all stores the user is authorized to access
        """
        try:
            authorized_store_ids = StoreAuthorization.objects.filter(
                user=user
            ).values_list('store_id', flat=True)
            
            return Store.objects.filter(id__in=authorized_store_ids)
        except Exception as e:
            logging.error(f"Error getting authorized stores for user {user.id}: {e}")
            return Store.objects.none()
    
    def validate_store_access(self, user: CustomUser, store_id: str) -> bool:
        """
        Validate if user has access to a specific store
        """
        try:
            return StoreAuthorization.objects.filter(
                user=user,
                store_id=store_id
            ).exists()
        except Exception as e:
            logging.error(f"Error validating store access: {e}")
            return False
    
    def filter_by_user_stores(self, queryset: QuerySet, user: CustomUser) -> QuerySet:
        """
        Filter a queryset to only include items from user's authorized stores
        """
        try:
            authorized_stores = self.get_user_authorized_stores(user)
            return queryset.filter(
                Q(source_store__in=authorized_stores) |
                Q(destination_store__in=authorized_stores)
            )
        except Exception as e:
            logging.error(f"Error filtering by user stores: {e}")
            return queryset.none()


class ICGInventoryService:
    """
    Service for ICG inventory management integration
    """
    
    def __init__(self):
        self.host = os.getenv('ICG_HOST')
        self.api_key = os.getenv('ICG_API_KEY')
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
    
    def update_inventory(self, store_id: str, product_id: str, quantity_change: float, operation: str) -> bool:
        """
        Update inventory in ICG system
        Args:
            store_id: The store identifier
            product_id: The product identifier  
            quantity_change: The quantity to add/subtract
            operation: 'add' or 'subtract'
        """
        try:
            # Mock implementation - would call ICG API
            logging.info(f"ICG inventory update: {operation} {quantity_change} of {product_id} at store {store_id}")
            return True
        except Exception as e:
            logging.error(f"Error updating ICG inventory: {e}")
            return False
    
    def get_inventory_level(self, store_id: str, product_id: str) -> float:
        """
        Get current inventory level for a product at a store
        """
        try:
            # Mock implementation - would call ICG API
            return 1000.0  # Mock inventory level
        except Exception as e:
            logging.error(f"Error getting inventory level: {e}")
            return 0.0