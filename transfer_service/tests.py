from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from egrn_service.models import Store
from .models import SalesOrder, SalesOrderLineItem, StoreAuthorization
from .services import SalesOrderService
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from .models import SalesOrder, SalesOrderLineItem, GoodsIssueNote, GoodsIssueLineItem, TransferReceiptNote, TransferReceiptLineItem

User = get_user_model()


class TransferServiceModelsTest(TestCase):
    """
    Basic tests to verify models are working correctly
    """
    
    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test stores
        self.source_store = Store.objects.create(
            store_name='Source Store',
            icg_warehouse_code='SRC001',
            byd_cost_center_code='CC001'
        )
        
        self.dest_store = Store.objects.create(
            store_name='Destination Store', 
            icg_warehouse_code='DST001',
            byd_cost_center_code='CC002'
        )
    
    def test_store_authorization_creation(self):
        """Test that StoreAuthorization can be created"""
        auth = StoreAuthorization.objects.create(
            user=self.user,
            store=self.source_store,
            role='manager'
        )
        
        self.assertEqual(auth.user, self.user)
        self.assertEqual(auth.store, self.source_store)
        self.assertEqual(auth.role, 'manager')
        self.assertIsNotNone(auth.created_date)
    
    def test_sales_order_creation(self):
        """Test that SalesOrder can be created"""
        sales_order = SalesOrder.objects.create(
            object_id='SO123456',
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=1000.00,
            order_date='2024-01-01'
        )
        
        self.assertEqual(sales_order.object_id, 'SO123456')
        self.assertEqual(sales_order.sales_order_id, 12345)
        self.assertEqual(sales_order.source_store, self.source_store)
        self.assertEqual(sales_order.destination_store, self.dest_store)
        self.assertEqual(str(sales_order), 'SO-12345')
    
    def test_models_import_correctly(self):
        """Test that all models can be imported"""
        from .models import (
            SalesOrder, SalesOrderLineItem,
            GoodsIssueNote, GoodsIssueLineItem,
            TransferReceiptNote, TransferReceiptLineItem,
            StoreAuthorization
        )
        
        # If we get here without errors, imports work
        self.assertTrue(True)


class SalesOrderCreationTest(TestCase):
    """
    Tests for SalesOrder creation and SAP ByD integration
    """
    
    def setUp(self):
        """Set up test data"""
        # Create test stores
        self.source_store = Store.objects.create(
            store_name='Source Store',
            icg_warehouse_code='SRC001',
            byd_cost_center_code='SELLER123'
        )
        
        self.dest_store = Store.objects.create(
            store_name='Destination Store', 
            icg_warehouse_code='DST001',
            byd_cost_center_code='BUYER456'
        )
        
        # Sample SAP ByD sales order data
        self.sample_sap_data = {
            "ObjectID": "SO123456789",
            "ID": "12345",
            "TotalNetAmount": "1500.00",
            "LastChangeDateTime": "/Date(1704067200000)/",  # 2024-01-01
            "DeliveryStatusCode": "1",
            "SellerParty": {
                "PartyID": "SELLER123",
                "PartyName": "Source Store"
            },
            "BuyerParty": {
                "PartyID": "BUYER456", 
                "PartyName": "Destination Store"
            },
            "Item": [
                {
                    "ObjectID": "ITEM001",
                    "ProductID": "PROD001",
                    "Description": "Test Product 1",
                    "Quantity": "10.000",
                    "ListUnitPriceAmount": "50.00",
                    "QuantityUnitCodeText": "EA"
                },
                {
                    "ObjectID": "ITEM002",
                    "ProductID": "PROD002", 
                    "Description": "Test Product 2",
                    "Quantity": "5.000",
                    "ListUnitPriceAmount": "200.00",
                    "QuantityUnitCodeText": "EA"
                }
            ]
        }
    
    def test_create_sales_order_success(self):
        """Test successful sales order creation from SAP ByD data"""
        sales_order = SalesOrder.create_sales_order(self.sample_sap_data.copy())
        
        # Verify sales order fields
        self.assertEqual(sales_order.object_id, "SO123456789")
        self.assertEqual(sales_order.sales_order_id, 12345)
        self.assertEqual(sales_order.total_net_amount, 1500.00)
        self.assertEqual(sales_order.source_store, self.source_store)
        self.assertEqual(sales_order.destination_store, self.dest_store)
        self.assertEqual(sales_order.delivery_status_code, "1")
        
        # Verify line items were created
        line_items = sales_order.line_items.all()
        self.assertEqual(line_items.count(), 2)
        
        # Verify first line item
        item1 = line_items.get(object_id="ITEM001")
        self.assertEqual(item1.product_id, "PROD001")
        self.assertEqual(item1.product_name, "Test Product 1")
        self.assertEqual(item1.quantity, 10.000)
        self.assertEqual(item1.unit_price, 50.00)
        self.assertEqual(item1.unit_of_measurement, "EA")
        
        # Verify second line item
        item2 = line_items.get(object_id="ITEM002")
        self.assertEqual(item2.product_id, "PROD002")
        self.assertEqual(item2.product_name, "Test Product 2")
        self.assertEqual(item2.quantity, 5.000)
        self.assertEqual(item2.unit_price, 200.00)
    
    def test_create_sales_order_missing_required_fields(self):
        """Test sales order creation fails with missing required fields"""
        # Test missing ObjectID
        data = self.sample_sap_data.copy()
        del data["ObjectID"]
        
        with self.assertRaises(ValidationError) as context:
            SalesOrder.create_sales_order(data)
        self.assertIn("Required field 'ObjectID' missing", str(context.exception))
        
        # Test missing ID
        data = self.sample_sap_data.copy()
        del data["ID"]
        
        with self.assertRaises(ValidationError) as context:
            SalesOrder.create_sales_order(data)
        self.assertIn("Required field 'ID' missing", str(context.exception))
    
    def test_create_sales_order_store_not_found(self):
        """Test sales order creation fails when stores are not found"""
        data = self.sample_sap_data.copy()
        data["SellerParty"]["PartyID"] = "NONEXISTENT"
        
        with self.assertRaises(ValidationError) as context:
            SalesOrder.create_sales_order(data)
        self.assertIn("Store not found for codes", str(context.exception))
    
    def test_create_sales_order_same_source_destination(self):
        """Test sales order creation fails when source and destination are the same"""
        data = self.sample_sap_data.copy()
        data["BuyerParty"]["PartyID"] = "SELLER123"  # Same as seller
        
        with self.assertRaises(ValidationError) as context:
            SalesOrder.create_sales_order(data)
        self.assertIn("Source and destination stores cannot be the same", str(context.exception))
    
    def test_create_sales_order_no_line_items(self):
        """Test sales order creation fails when no line items are provided"""
        data = self.sample_sap_data.copy()
        data["Item"] = []
        
        with self.assertRaises(Exception) as context:
            SalesOrder.create_sales_order(data)
        self.assertIn("No line items were created", str(context.exception))
    
    def test_create_sales_order_line_item_error_rollback(self):
        """Test sales order is deleted if line item creation fails"""
        data = self.sample_sap_data.copy()
        # Create invalid line item data
        data["Item"][0]["Quantity"] = "invalid_number"
        
        initial_count = SalesOrder.objects.count()
        
        with self.assertRaises(Exception):
            SalesOrder.create_sales_order(data)
        
        # Verify sales order was not created due to rollback
        self.assertEqual(SalesOrder.objects.count(), initial_count)
    
    def test_find_store_by_identifier_multiple_methods(self):
        """Test store finding by different identifier types"""
        # Test by byd_cost_center_code
        store = SalesOrder._find_store_by_identifier("SELLER123")
        self.assertEqual(store, self.source_store)
        
        # Test by icg_warehouse_code
        store = SalesOrder._find_store_by_identifier("SRC001")
        self.assertEqual(store, self.source_store)
        
        # Test by ID
        store = SalesOrder._find_store_by_identifier(str(self.source_store.id))
        self.assertEqual(store, self.source_store)
        
        # Test nonexistent identifier
        with self.assertRaises(Store.DoesNotExist):
            SalesOrder._find_store_by_identifier("NONEXISTENT")


class SalesOrderServiceTest(TestCase):
    """
    Tests for SalesOrderService SAP ByD integration
    """
    
    def setUp(self):
        """Set up test data"""
        self.service = SalesOrderService()
        
        # Create test stores
        self.source_store = Store.objects.create(
            store_name='Source Store',
            icg_warehouse_code='SRC001',
            byd_cost_center_code='SELLER123'
        )
        
        self.dest_store = Store.objects.create(
            store_name='Destination Store', 
            icg_warehouse_code='DST001',
            byd_cost_center_code='BUYER456'
        )
    
    @patch('byd_service.rest.RESTServices')
    def test_fetch_sales_order_by_id_success(self, mock_rest_services):
        """Test successful sales order fetch from SAP ByD"""
        # Mock the REST service response
        mock_rest_instance = Mock()
        mock_rest_services.return_value = mock_rest_instance
        mock_rest_instance.get_sales_order_by_id.return_value = {
            "ObjectID": "SO123456789",
            "ID": "12345",
            "TotalNetAmount": "1500.00"
        }
        
        service = SalesOrderService()
        result = service.fetch_sales_order_by_id("12345")
        
        self.assertIsNotNone(result)
        self.assertEqual(result["ID"], "12345")
        mock_rest_instance.get_sales_order_by_id.assert_called_once_with("12345")
    
    @patch('byd_service.rest.RESTServices')
    def test_get_store_sales_orders_success(self, mock_rest_services):
        """Test successful store sales orders fetch from SAP ByD"""
        # Mock the REST service response
        mock_rest_instance = Mock()
        mock_rest_services.return_value = mock_rest_instance
        mock_rest_instance.get_store_sales_orders.return_value = [
            {"ID": "12345", "TotalNetAmount": "1500.00"},
            {"ID": "12346", "TotalNetAmount": "2000.00"}
        ]
        
        service = SalesOrderService()
        result = service.get_store_sales_orders("STORE001")
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["ID"], "12345")
        mock_rest_instance.get_store_sales_orders.assert_called_once_with("STORE001")
    
    @patch('byd_service.rest.RESTServices')
    def test_update_sales_order_status_success(self, mock_rest_services):
        """Test successful sales order status update in SAP ByD"""
        # Mock the REST service response
        mock_rest_instance = Mock()
        mock_rest_services.return_value = mock_rest_instance
        mock_rest_instance.update_sales_order_status.return_value = True
        
        service = SalesOrderService()
        result = service.update_sales_order_status("12345", "3")
        
        self.assertTrue(result)
        mock_rest_instance.update_sales_order_status.assert_called_once_with("12345", "3")
    
    @patch('transfer_service.services.SalesOrderService.fetch_sales_order_by_id')
    def test_create_or_update_local_sales_order_new(self, mock_fetch):
        """Test creating new local sales order from SAP ByD data"""
        # Mock SAP ByD data
        mock_fetch.return_value = {
            "ObjectID": "SO123456789",
            "ID": "12345",
            "TotalNetAmount": "1500.00",
            "LastChangeDateTime": "/Date(1704067200000)/",
            "SellerParty": {"PartyID": "SELLER123"},
            "BuyerParty": {"PartyID": "BUYER456"},
            "Item": [
                {
                    "ObjectID": "ITEM001",
                    "ProductID": "PROD001",
                    "Description": "Test Product",
                    "Quantity": "10.000",
                    "ListUnitPriceAmount": "50.00",
                    "QuantityUnitCodeText": "EA"
                }
            ]
        }
        
        result = self.service.create_or_update_local_sales_order("12345")
        
        self.assertIsNotNone(result)
        self.assertEqual(result.sales_order_id, 12345)
        self.assertEqual(result.object_id, "SO123456789")
        mock_fetch.assert_called_once_with("12345")
    
    def test_create_or_update_local_sales_order_existing(self):
        """Test returning existing local sales order"""
        # Create existing sales order
        existing_so = SalesOrder.objects.create(
            object_id='SO123456789',
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=1500.00,
            order_date='2024-01-01'
        )
        
        with patch.object(self.service, 'fetch_sales_order_by_id') as mock_fetch:
            result = self.service.create_or_update_local_sales_order("12345")
            
            self.assertEqual(result, existing_so)
            # Should not call SAP ByD since order exists locally
            mock_fetch.assert_not_called()
    
    @patch('transfer_service.services.SalesOrderService.fetch_sales_order_by_id')
    def test_create_or_update_local_sales_order_not_found_in_sap(self, mock_fetch):
        """Test handling when sales order is not found in SAP ByD"""
        mock_fetch.return_value = None
        
        with self.assertRaises(ValidationError) as context:
            self.service.create_or_update_local_sales_order("99999")
        
        self.assertIn("not found in SAP ByD", str(context.exception))


class SalesOrderPropertiesTest(TestCase):
    """
    Tests for SalesOrder calculated properties and status management
    """
    
    def setUp(self):
        """Set up test data"""
        # Create test stores
        self.source_store = Store.objects.create(
            store_name='Source Store',
            icg_warehouse_code='SRC001',
            byd_cost_center_code='SELLER123'
        )
        
        self.dest_store = Store.objects.create(
            store_name='Destination Store', 
            icg_warehouse_code='DST001',
            byd_cost_center_code='BUYER456'
        )
        
        # Create test sales order
        self.sales_order = SalesOrder.objects.create(
            object_id='SO123456789',
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=1500.00,
            order_date='2024-01-01'
        )
        
        # Create test line items
        self.line_item1 = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id='ITEM001',
            product_id='PROD001',
            product_name='Test Product 1',
            quantity=10.000,
            unit_price=50.00,
            unit_of_measurement='EA'
        )
        
        self.line_item2 = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id='ITEM002',
            product_id='PROD002',
            product_name='Test Product 2',
            quantity=5.000,
            unit_price=200.00,
            unit_of_measurement='EA'
        )
    
    def test_delivery_status_not_started(self):
        """Test delivery status when no items have been issued"""
        status = self.sales_order.delivery_status
        self.assertEqual(status[0], '1')  # Not Started
        self.assertEqual(status[1], 'Not Started')
    
    def test_issued_and_received_quantities_zero(self):
        """Test issued and received quantities when no goods have been processed"""
        self.assertEqual(self.sales_order.issued_quantity, 0.0)
        self.assertEqual(self.sales_order.received_quantity, 0.0)
    
    def test_line_item_properties(self):
        """Test line item calculated properties"""
        # Test initial state
        self.assertEqual(self.line_item1.issued_quantity, 0.0)
        self.assertEqual(self.line_item1.received_quantity, 0.0)
        
        status = self.line_item1.delivery_status
        self.assertEqual(status[0], '1')  # Not Started
        self.assertEqual(status[1], 'Not Started')


class TransferServiceAPITests(APITestCase):
    def setUp(self):
        from core_service.models import CustomUser
        self.user = CustomUser.objects.create_user(username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        
        # Create Store objects for testing
        self.source_store = Store.objects.create(
            store_name='Source Store',
            byd_cost_center_code='SRC001',
            icg_warehouse_code='SRC_WH'
        )
        self.destination_store = Store.objects.create(
            store_name='Destination Store',
            byd_cost_center_code='DST001',
            icg_warehouse_code='DST_WH'
        )
        
        # Minimal SalesOrder and related objects
        self.sales_order = SalesOrder.objects.create(
            object_id='so1', sales_order_id=1, 
            source_store=self.source_store, destination_store=self.destination_store,
            total_net_amount=100, order_date='2023-01-01', delivery_status_code='1', metadata={}
        )
        self.sales_order_line = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order, object_id='sol1', product_id='p1', product_name='Test Product',
            quantity=10, unit_price=10, unit_of_measurement='pcs', metadata={}
        )
        self.goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order, issue_number=1, source_store=self.source_store, created_by=self.user
        )
        self.goods_issue_line = GoodsIssueLineItem.objects.create(
            goods_issue=self.goods_issue, sales_order_line_item=self.sales_order_line, quantity_issued=5, metadata={}
        )
        self.transfer_receipt = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue, receipt_number=1, destination_store=self.destination_store, created_by=self.user
        )
        self.transfer_receipt_line = TransferReceiptLineItem.objects.create(
            transfer_receipt=self.transfer_receipt, goods_issue_line_item=self.goods_issue_line, quantity_received=5, metadata={}
        )

    def test_sales_order_list(self):
        url = reverse('salesorder-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue('results' in response.data or isinstance(response.data, list))

    def test_sales_order_detail(self):
        url = reverse('salesorder-detail', args=[self.sales_order.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.sales_order.pk)

    def test_goods_issue_list(self):
        url = reverse('goodsissuenote-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_goods_issue_detail(self):
        url = reverse('goodsissuenote-detail', args=[self.goods_issue.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.goods_issue.pk)

    def test_transfer_receipt_list(self):
        url = reverse('transferreceiptnote-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_transfer_receipt_detail(self):
        url = reverse('transferreceiptnote-detail', args=[self.transfer_receipt.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.transfer_receipt.pk)