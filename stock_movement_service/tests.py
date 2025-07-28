import json
from datetime import date, datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock

from egrn_service.models import Store
from .models import (
    SalesOrder, SalesOrderLineItem, GoodsIssueNote, GoodsIssueLineItem,
    TransferReceiptNote, TransferReceiptLineItem, StoreAuthorization,
    DELIVERY_STATUS_CHOICES
)
from .services import SalesOrderService, GoodsIssueService, TransferReceiptService, AuthorizationService

User = get_user_model()


class SalesOrderModelTest(TestCase):
    """Test SalesOrder model functionality"""
    
    def setUp(self):
        # Create test stores
        self.source_store = Store.objects.create(
            store_name="Source Store",
            icg_warehouse_code="SRC001",
            byd_cost_center_code="STORE001"
        )
        self.destination_store = Store.objects.create(
            store_name="Destination Store", 
            icg_warehouse_code="DST001",
            byd_cost_center_code="STORE002"
        )
    
    def test_sales_order_creation(self):
        """Test creating a sales order"""
        sales_order = SalesOrder.objects.create(
            object_id="TEST001",
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.destination_store,
            total_net_amount=Decimal('1000.00'),
            order_date=date.today()
        )
        
        self.assertEqual(str(sales_order), "SO-12345")
        self.assertEqual(sales_order.delivery_status[0], '1')  # Not delivered
        self.assertEqual(sales_order.source_store, self.source_store)
        self.assertEqual(sales_order.destination_store, self.destination_store)
    
    def test_sales_order_delivery_status(self):
        """Test delivery status calculation"""
        sales_order = SalesOrder.objects.create(
            object_id="TEST002",
            sales_order_id=12346,
            source_store=self.source_store,
            destination_store=self.destination_store,
            total_net_amount=Decimal('1000.00'),
            order_date=date.today()
        )
        
        # Initially not delivered
        self.assertEqual(sales_order.delivery_status[0], '1')
        
        # Add line item
        line_item = SalesOrderLineItem.objects.create(
            sales_order=sales_order,
            object_id="LINE001",
            product_id="PROD001",
            product_name="Test Product",
            quantity=Decimal('10.00'),
            unit_price=Decimal('100.00'),
            unit_of_measurement="EA"
        )
        
        # Still not delivered (no goods issued)
        self.assertEqual(sales_order.delivery_status[0], '1')


class SalesOrderLineItemModelTest(TestCase):
    """Test SalesOrderLineItem model functionality"""
    
    def setUp(self):
        self.source_store = Store.objects.create(
            store_name="Source Store",
            icg_warehouse_code="SRC001", 
            byd_cost_center_code="STORE001"
        )
        self.destination_store = Store.objects.create(
            store_name="Destination Store",
            icg_warehouse_code="DST001",
            byd_cost_center_code="STORE002"
        )
        
        self.sales_order = SalesOrder.objects.create(
            object_id="TEST001",
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.destination_store,
            total_net_amount=Decimal('1000.00'),
            order_date=date.today()
        )
    
    def test_line_item_creation(self):
        """Test creating a sales order line item"""
        line_item = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id="LINE001",
            product_id="PROD001",
            product_name="Test Product",
            quantity=Decimal('10.00'),
            unit_price=Decimal('100.00'),
            unit_of_measurement="EA"
        )
        
        self.assertEqual(str(line_item), "SO-12345: Test Product (10.000)")
        self.assertEqual(line_item.issued_quantity, 0.0)
        self.assertEqual(line_item.received_quantity, 0.0)
        self.assertEqual(line_item.delivery_status[0], '1')  # Not delivered


class GoodsIssueModelTest(TestCase):
    """Test GoodsIssueNote and GoodsIssueLineItem models"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        
        self.source_store = Store.objects.create(
            store_name="Source Store",
            icg_warehouse_code="SRC001",
            byd_cost_center_code="STORE001"
        )
        self.destination_store = Store.objects.create(
            store_name="Destination Store",
            icg_warehouse_code="DST001", 
            byd_cost_center_code="STORE002"
        )
        
        self.sales_order = SalesOrder.objects.create(
            object_id="TEST001",
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.destination_store,
            total_net_amount=Decimal('1000.00'),
            order_date=date.today()
        )
        
        self.line_item = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id="LINE001",
            product_id="PROD001", 
            product_name="Test Product",
            quantity=Decimal('10.00'),
            unit_price=Decimal('100.00'),
            unit_of_measurement="EA"
        )
    
    def test_goods_issue_creation(self):
        """Test creating a goods issue note"""
        goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order,
            source_store=self.source_store,
            created_by=self.user
        )
        
        self.assertTrue(goods_issue.issue_number > 0)
        self.assertEqual(str(goods_issue), f"Issue #{goods_issue.issue_number}")
        self.assertEqual(goods_issue.total_issued_value, 0)  # No line items yet
    
    def test_goods_issue_line_item_validation(self):
        """Test goods issue line item validation"""
        goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order,
            source_store=self.source_store,
            created_by=self.user
        )
        
        # Test valid quantity
        issue_line_item = GoodsIssueLineItem(
            goods_issue=goods_issue,
            sales_order_line_item=self.line_item,
            quantity_issued=Decimal('5.00')
        )
        # Should not raise exception
        issue_line_item.clean()
        issue_line_item.save()
        
        self.assertEqual(issue_line_item.issued_value, 500.00)  # 5 * 100
        
        # Test invalid quantity (exceeds available)
        invalid_issue_item = GoodsIssueLineItem(
            goods_issue=goods_issue,
            sales_order_line_item=self.line_item,
            quantity_issued=Decimal('15.00')  # More than available (10)
        )
        
        with self.assertRaises(ValidationError):
            invalid_issue_item.clean()


class TransferReceiptModelTest(TestCase):
    """Test TransferReceiptNote and TransferReceiptLineItem models"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com", 
            password="testpass123"
        )
        
        self.source_store = Store.objects.create(
            store_name="Source Store",
            icg_warehouse_code="SRC001",
            byd_cost_center_code="STORE001"
        )
        self.destination_store = Store.objects.create(
            store_name="Destination Store",
            icg_warehouse_code="DST001",
            byd_cost_center_code="STORE002"
        )
        
        self.sales_order = SalesOrder.objects.create(
            object_id="TEST001",
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.destination_store,
            total_net_amount=Decimal('1000.00'),
            order_date=date.today()
        )
        
        self.line_item = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id="LINE001",
            product_id="PROD001",
            product_name="Test Product",
            quantity=Decimal('10.00'),
            unit_price=Decimal('100.00'),
            unit_of_measurement="EA"
        )
        
        self.goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order,
            source_store=self.source_store,
            created_by=self.user
        )
        
        self.issue_line_item = GoodsIssueLineItem.objects.create(
            goods_issue=self.goods_issue,
            sales_order_line_item=self.line_item,
            quantity_issued=Decimal('8.00')
        )
    
    def test_transfer_receipt_creation(self):
        """Test creating a transfer receipt note"""
        transfer_receipt = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.destination_store,
            created_by=self.user
        )
        
        self.assertTrue(transfer_receipt.receipt_number > 0)
        self.assertEqual(str(transfer_receipt), f"Receipt #{transfer_receipt.receipt_number}")
        self.assertEqual(transfer_receipt.total_received_value, 0)  # No line items yet
    
    def test_transfer_receipt_line_item_validation(self):
        """Test transfer receipt line item validation"""
        transfer_receipt = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.destination_store,
            created_by=self.user
        )
        
        # Test valid quantity
        receipt_line_item = TransferReceiptLineItem(
            transfer_receipt=transfer_receipt,
            goods_issue_line_item=self.issue_line_item,
            quantity_received=Decimal('6.00')
        )
        receipt_line_item.clean()
        receipt_line_item.save()
        
        self.assertEqual(receipt_line_item.received_value, 600.00)  # 6 * 100
        
        # Test invalid quantity (exceeds issued)
        invalid_receipt_item = TransferReceiptLineItem(
            transfer_receipt=transfer_receipt,
            goods_issue_line_item=self.issue_line_item,
            quantity_received=Decimal('10.00')  # More than issued (8)
        )
        
        with self.assertRaises(ValidationError):
            invalid_receipt_item.clean()


class StoreAuthorizationModelTest(TestCase):
    """Test StoreAuthorization model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        
        self.store = Store.objects.create(
            store_name="Test Store",
            icg_warehouse_code="TST001",
            byd_cost_center_code="STORE001"
        )
    
    def test_store_authorization_creation(self):
        """Test creating store authorization"""
        authorization = StoreAuthorization.objects.create(
            user=self.user,
            store=self.store,
            role='manager'
        )
        
        expected_str = f"{self.user.email} - {self.store.store_name} (manager)"
        self.assertEqual(str(authorization), expected_str)
    
    def test_unique_user_store_constraint(self):
        """Test unique constraint on user-store pair"""
        StoreAuthorization.objects.create(
            user=self.user,
            store=self.store,
            role='manager'
        )
        
        # Try to create duplicate
        with self.assertRaises(Exception):  # IntegrityError
            StoreAuthorization.objects.create(
                user=self.user,
                store=self.store,
                role='assistant'
            )


class SalesOrderServiceTest(TestCase):
    """Test SalesOrderService functionality"""
    
    def setUp(self):
        self.service = SalesOrderService()
    
    def test_fetch_sales_order_by_id(self):
        """Test fetching sales order by ID"""
        # Test with mock data
        result = self.service.fetch_sales_order_by_id("59461")
        
        self.assertIsNotNone(result)
        self.assertEqual(result["ID"], 59461)
        self.assertEqual(result["SourceStoreID"], "STORE001")
        self.assertEqual(result["DestinationStoreID"], "STORE002")
    
    def test_fetch_nonexistent_sales_order(self):
        """Test fetching non-existent sales order"""
        result = self.service.fetch_sales_order_by_id("99999")
        
        self.assertIsNone(result)
    
    def test_get_store_sales_orders(self):
        """Test getting sales orders for a store"""
        orders = self.service.get_store_sales_orders("STORE001")
        
        self.assertIsInstance(orders, list)
        # Should return orders where STORE001 is source or destination
        self.assertTrue(len(orders) > 0)
    
    def test_update_sales_order_status(self):
        """Test updating sales order status"""
        result = self.service.update_sales_order_status("59461", "COMPLETED")
        
        self.assertTrue(result)


class AuthorizationServiceTest(TestCase):
    """Test AuthorizationService functionality"""
    
    def setUp(self):
        self.service = AuthorizationService()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        
        self.store1 = Store.objects.create(
            store_name="Store 1",
            icg_warehouse_code="ST1001",
            byd_cost_center_code="STORE001"
        )
        self.store2 = Store.objects.create(
            store_name="Store 2", 
            icg_warehouse_code="ST2001",
            byd_cost_center_code="STORE002"
        )
        
        # Give user access to store1
        StoreAuthorization.objects.create(
            user=self.user,
            store=self.store1,
            role='manager'
        )
    
    def test_get_user_authorized_stores(self):
        """Test getting user's authorized stores"""
        stores = self.service.get_user_authorized_stores(self.user)
        
        self.assertEqual(stores.count(), 1)
        self.assertEqual(stores.first(), self.store1)
    
    def test_validate_store_access(self):
        """Test validating store access"""
        # User has access to store1
        self.assertTrue(self.service.validate_store_access(self.user, self.store1.id))
        
        # User does not have access to store2
        self.assertFalse(self.service.validate_store_access(self.user, self.store2.id))


class StockMovementAPITest(APITestCase):
    """Test API endpoints for stock movement service"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        
        self.source_store = Store.objects.create(
            store_name="Source Store",
            icg_warehouse_code="SRC001",
            byd_cost_center_code="STORE001"
        )
        self.destination_store = Store.objects.create(
            store_name="Destination Store",
            icg_warehouse_code="DST001",
            byd_cost_center_code="STORE002"
        )
        
        # Give user access to both stores
        StoreAuthorization.objects.create(
            user=self.user,
            store=self.source_store,
            role='manager'
        )
        StoreAuthorization.objects.create(
            user=self.user,
            store=self.destination_store,
            role='manager'
        )
        
        self.sales_order = SalesOrder.objects.create(
            object_id="TEST001",
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.destination_store,
            total_net_amount=Decimal('1000.00'),
            order_date=date.today()
        )
        
        self.line_item = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id="LINE001",
            product_id="PROD001",
            product_name="Test Product",
            quantity=Decimal('10.00'),
            unit_price=Decimal('100.00'),
            unit_of_measurement="EA"
        )
        
        # Mock authentication
        self.client.force_authenticate(user=self.user)
    
    def test_get_sales_orders(self):
        """Test GET /sales-orders endpoint"""
        url = '/stock-movement/v1/sales-orders'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
    
    def test_get_sales_order_by_id(self):
        """Test GET /sales-orders/{id} endpoint"""
        url = f'/stock-movement/v1/sales-orders/{self.sales_order.sales_order_id}'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['sales_order_id'], self.sales_order.sales_order_id)
    
    @patch('stock_movement_service.services.GoodsIssueService.validate_inventory_availability')
    def test_create_goods_issue(self, mock_validate):
        """Test POST /goods-issue endpoint"""
        mock_validate.return_value = True
        
        url = '/stock-movement/v1/goods-issue'
        data = {
            'sales_order_id': self.sales_order.sales_order_id,
            'issued_goods': [
                {
                    'itemObjectID': self.line_item.object_id,
                    'productID': self.line_item.product_id,
                    'quantityIssued': '5.00'
                }
            ]
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])
        
        # Verify goods issue was created
        self.assertTrue(GoodsIssueNote.objects.filter(sales_order=self.sales_order).exists())
    
    def test_get_user_store_authorizations(self):
        """Test GET /user-store-authorizations endpoint"""
        url = '/stock-movement/v1/user-store-authorizations'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(len(response.data['data']), 2)  # User has access to 2 stores


class IntegrationTest(TestCase):
    """Integration tests for complete transfer workflow"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        
        self.source_store = Store.objects.create(
            store_name="Source Store",
            icg_warehouse_code="SRC001",
            byd_cost_center_code="STORE001"
        )
        self.destination_store = Store.objects.create(
            store_name="Destination Store",
            icg_warehouse_code="DST001",
            byd_cost_center_code="STORE002"
        )
        
        # Give user access to both stores
        StoreAuthorization.objects.create(
            user=self.user,
            store=self.source_store,
            role='manager'
        )
        StoreAuthorization.objects.create(
            user=self.user,
            store=self.destination_store,
            role='manager'
        )
    
    def test_complete_transfer_workflow(self):
        """Test complete transfer workflow from sales order to receipt"""
        # 1. Create sales order
        sales_order = SalesOrder.objects.create(
            object_id="INTEGRATION001",
            sales_order_id=99999,
            source_store=self.source_store,
            destination_store=self.destination_store,
            total_net_amount=Decimal('2000.00'),
            order_date=date.today()
        )
        
        # 2. Add line items
        line_item1 = SalesOrderLineItem.objects.create(
            sales_order=sales_order,
            object_id="LINE001",
            product_id="PROD001",
            product_name="Product 1",
            quantity=Decimal('10.00'),
            unit_price=Decimal('100.00'),
            unit_of_measurement="EA"
        )
        
        line_item2 = SalesOrderLineItem.objects.create(
            sales_order=sales_order,
            object_id="LINE002",
            product_id="PROD002",
            product_name="Product 2",
            quantity=Decimal('5.00'),
            unit_price=Decimal('200.00'),
            unit_of_measurement="EA"
        )
        
        # 3. Create goods issue
        goods_issue = GoodsIssueNote.objects.create(
            sales_order=sales_order,
            source_store=self.source_store,
            created_by=self.user
        )
        
        # 4. Add goods issue line items
        issue_item1 = GoodsIssueLineItem.objects.create(
            goods_issue=goods_issue,
            sales_order_line_item=line_item1,
            quantity_issued=Decimal('8.00')  # Partial issue
        )
        
        issue_item2 = GoodsIssueLineItem.objects.create(
            goods_issue=goods_issue,
            sales_order_line_item=line_item2,
            quantity_issued=Decimal('5.00')  # Full issue
        )
        
        # 5. Create transfer receipt
        transfer_receipt = TransferReceiptNote.objects.create(
            goods_issue=goods_issue,
            destination_store=self.destination_store,
            created_by=self.user
        )
        
        # 6. Add transfer receipt line items
        receipt_item1 = TransferReceiptLineItem.objects.create(
            transfer_receipt=transfer_receipt,
            goods_issue_line_item=issue_item1,
            quantity_received=Decimal('7.00')  # Partial receipt
        )
        
        receipt_item2 = TransferReceiptLineItem.objects.create(
            transfer_receipt=transfer_receipt,
            goods_issue_line_item=issue_item2,
            quantity_received=Decimal('5.00')  # Full receipt
        )
        
        # 7. Verify workflow completion
        # Check issued quantities
        self.assertEqual(line_item1.issued_quantity, Decimal('8.00'))
        self.assertEqual(line_item2.issued_quantity, Decimal('5.00'))
        
        # Check received quantities
        self.assertEqual(line_item1.received_quantity, Decimal('7.00'))
        self.assertEqual(line_item2.received_quantity, Decimal('5.00'))
        
        # Check delivery status (should be partially delivered since line_item1 not fully issued)
        self.assertEqual(sales_order.delivery_status[0], '2')  # Partially delivered
        
        # Check total values
        self.assertEqual(goods_issue.total_issued_value, 1800.00)  # 8*100 + 5*200
        self.assertEqual(transfer_receipt.total_received_value, 1700.00)  # 7*100 + 5*200