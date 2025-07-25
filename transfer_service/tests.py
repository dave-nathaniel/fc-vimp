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


class GoodsIssueCreationViewTest(APITestCase):
    """
    Tests for the goods issue creation view
    """
    
    def setUp(self):
        """Set up test data"""
        from core_service.models import CustomUser
        
        # Create test users
        self.user = CustomUser.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.unauthorized_user = CustomUser.objects.create_user(
            username='unauthorized',
            email='unauthorized@example.com',
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
        
        # Create store authorization for the user
        StoreAuthorization.objects.create(
            user=self.user,
            store=self.source_store,
            role='manager'
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
        
        # Authenticate the user
        self.client.force_authenticate(user=self.user)
    
    def test_create_goods_issue_success(self):
        """Test successful goods issue creation"""
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': 8.0,
                    'metadata': {}
                },
                {
                    'sales_order_line_item': self.line_item2.id,
                    'quantity_issued': 3.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.check_inventory_availability') as mock_inventory:
            with patch('transfer_service.views.send_goods_issue_notification') as mock_notification:
                mock_inventory.return_value = True
                mock_notification.return_value = True
                
                response = self.client.post(url, data, format='json')
                
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertTrue(response.data['success'])
                self.assertIn('GI-', response.data['message'])
                self.assertTrue(response.data['notification_sent'])
                
                # Verify goods issue was created
                goods_issue = GoodsIssueNote.objects.get(sales_order=self.sales_order)
                self.assertEqual(goods_issue.source_store, self.source_store)
                self.assertEqual(goods_issue.created_by, self.user)
                self.assertEqual(goods_issue.line_items.count(), 2)
                
                # Verify line items
                line_items = goods_issue.line_items.all()
                self.assertEqual(line_items.filter(quantity_issued=8.0).count(), 1)
                self.assertEqual(line_items.filter(quantity_issued=3.0).count(), 1)
    
    def test_create_goods_issue_unauthorized_store(self):
        """Test goods issue creation fails for unauthorized store"""
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.dest_store.id,  # User not authorized for this store
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(url, data, format='json')
        
        # The serializer validation catches this first, so it returns 400 instead of 403
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')
        self.assertIn('not authorized', str(response.data['details']))
    
    def test_create_goods_issue_unauthorized_user(self):
        """Test goods issue creation fails for unauthorized user"""
        self.client.force_authenticate(user=self.unauthorized_user)
        
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')
    
    def test_create_goods_issue_insufficient_inventory(self):
        """Test goods issue creation fails when inventory is insufficient"""
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.check_inventory_availability') as mock_inventory:
            mock_inventory.return_value = False
            
            response = self.client.post(url, data, format='json')
            
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(response.data['success'])
            self.assertEqual(response.data['error_code'], 'INVENTORY_INSUFFICIENT')
            self.assertIn('Insufficient inventory', response.data['message'])
    
    def test_create_goods_issue_invalid_data(self):
        """Test goods issue creation fails with invalid data"""
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': -5.0,  # Invalid negative quantity
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')
        self.assertIn('field_errors', response.data['details'])
    
    def test_create_goods_issue_missing_line_items(self):
        """Test goods issue creation fails without line items"""
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [],  # Empty line items
            'metadata': {}
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')
    
    def test_create_goods_issue_wrong_source_store(self):
        """Test goods issue creation fails when source store doesn't match sales order"""
        # Create another store
        wrong_store = Store.objects.create(
            store_name='Wrong Store',
            icg_warehouse_code='WRG001',
            byd_cost_center_code='CC003'
        )
        
        # Give user authorization for wrong store
        StoreAuthorization.objects.create(
            user=self.user,
            store=wrong_store,
            role='manager'
        )
        
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': wrong_store.id,  # Wrong source store
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')
    
    def test_create_goods_issue_line_item_wrong_sales_order(self):
        """Test goods issue creation fails when line item belongs to different sales order"""
        # Create another sales order
        other_sales_order = SalesOrder.objects.create(
            object_id='SO987654321',
            sales_order_id=54321,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=500.00,
            order_date='2024-01-02'
        )
        
        other_line_item = SalesOrderLineItem.objects.create(
            sales_order=other_sales_order,
            object_id='ITEM003',
            product_id='PROD003',
            product_name='Other Product',
            quantity=3.000,
            unit_price=100.00,
            unit_of_measurement='EA'
        )
        
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [
                {
                    'sales_order_line_item': other_line_item.id,  # Wrong sales order
                    'quantity_issued': 2.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')
    
    def test_create_goods_issue_quantity_exceeds_available(self):
        """Test goods issue creation fails when quantity exceeds available"""
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': 15.0,  # Exceeds available quantity of 10
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.check_inventory_availability') as mock_inventory:
            mock_inventory.return_value = True
            
            response = self.client.post(url, data, format='json')
            
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(response.data['success'])
            self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')
    
    def test_create_goods_issue_notification_failure(self):
        """Test goods issue creation succeeds even if notification fails"""
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.check_inventory_availability') as mock_inventory:
            with patch('transfer_service.views.send_goods_issue_notification') as mock_notification:
                mock_inventory.return_value = True
                mock_notification.return_value = False  # Notification fails
                
                response = self.client.post(url, data, format='json')
                
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertTrue(response.data['success'])
                self.assertFalse(response.data['notification_sent'])
                
                # Verify goods issue was still created
                self.assertTrue(GoodsIssueNote.objects.filter(sales_order=self.sales_order).exists())
    
    def test_create_goods_issue_unauthenticated(self):
        """Test goods issue creation fails for unauthenticated user"""
        self.client.force_authenticate(user=None)
        
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    @patch('transfer_service.views.logger')
    def test_create_goods_issue_internal_error(self, mock_logger):
        """Test goods issue creation handles internal errors gracefully"""
        url = reverse('create-goods-issue')
        data = {
            'sales_order': self.sales_order.id,
            'source_store': self.source_store.id,
            'line_items': [
                {
                    'sales_order_line_item': self.line_item1.id,
                    'quantity_issued': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.check_inventory_availability') as mock_inventory:
            with patch('transfer_service.serializers.GoodsIssueNoteCreateSerializer.save') as mock_save:
                mock_inventory.return_value = True
                mock_save.side_effect = Exception("Database error")
                
                response = self.client.post(url, data, format='json')
                
                self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
                self.assertFalse(response.data['success'])
                self.assertEqual(response.data['error_code'], 'INTERNAL_ERROR')
                mock_logger.error.assert_called_once()


class InventoryAvailabilityCheckTest(TestCase):
    """
    Tests for inventory availability checking (placeholder implementation)
    """
    
    def setUp(self):
        """Set up test data"""
        self.store = Store.objects.create(
            store_name='Test Store',
            icg_warehouse_code='TST001',
            byd_cost_center_code='CC001'
        )
        
        self.line_items = [
            {
                'sales_order_line_item': Mock(product_id='PROD001'),
                'quantity_issued': 10.0
            },
            {
                'sales_order_line_item': Mock(product_id='PROD002'),
                'quantity_issued': 5.0
            }
        ]
    
    def test_check_inventory_availability_placeholder(self):
        """Test inventory availability check placeholder function"""
        from transfer_service.views import check_inventory_availability
        
        # Placeholder implementation should return True
        result = check_inventory_availability(self.store.id, self.line_items)
        self.assertTrue(result)


class GoodsIssueNotificationTest(TestCase):
    """
    Tests for goods issue email notification functionality
    """
    
    def setUp(self):
        """Set up test data"""
        from core_service.models import CustomUser
        
        # Create test users
        self.user = CustomUser.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.manager1 = CustomUser.objects.create_user(
            username='manager1',
            email='manager1@example.com',
            password='testpass123'
        )
        
        self.manager2 = CustomUser.objects.create_user(
            username='manager2',
            email='manager2@example.com',
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
        
        # Create store authorizations for managers
        StoreAuthorization.objects.create(
            user=self.manager1,
            store=self.dest_store,
            role='manager'
        )
        
        StoreAuthorization.objects.create(
            user=self.manager2,
            store=self.dest_store,
            role='assistant'
        )
        
        # Create test sales order and goods issue
        self.sales_order = SalesOrder.objects.create(
            object_id='SO123456789',
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=1500.00,
            order_date='2024-01-01'
        )
        
        self.goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order,
            issue_number=12345,
            source_store=self.source_store,
            created_by=self.user
        )
    
    @patch('transfer_service.views.EmailMessage')
    @patch('transfer_service.views.render_to_string')
    def test_send_goods_issue_notification_success(self, mock_render, mock_email):
        """Test successful goods issue notification sending"""
        from transfer_service.views import send_goods_issue_notification
        
        mock_render.return_value = '<html>Test email content</html>'
        mock_email_instance = Mock()
        mock_email.return_value = mock_email_instance
        mock_email_instance.send.return_value = True
        
        result = send_goods_issue_notification(self.goods_issue)
        
        self.assertTrue(result)
        mock_render.assert_called_once()
        mock_email.assert_called_once()
        mock_email_instance.send.assert_called_once()
        
        # Verify email was sent to both managers
        call_args = mock_email.call_args
        self.assertIn('manager1@example.com', call_args[1]['to'])
        self.assertIn('manager2@example.com', call_args[1]['to'])
        self.assertIn('GI-12345', call_args[1]['subject'])
    
    def test_send_goods_issue_notification_no_managers(self):
        """Test notification handling when no managers are found"""
        from transfer_service.views import send_goods_issue_notification
        
        # Remove all store authorizations
        StoreAuthorization.objects.filter(store=self.dest_store).delete()
        
        result = send_goods_issue_notification(self.goods_issue)
        
        self.assertFalse(result)
    
    def test_send_goods_issue_notification_no_email_addresses(self):
        """Test notification handling when managers have no email addresses"""
        from transfer_service.views import send_goods_issue_notification
        
        # Remove email addresses from managers
        self.manager1.email = ''
        self.manager1.save()
        self.manager2.email = ''
        self.manager2.save()
        
        result = send_goods_issue_notification(self.goods_issue)
        
        self.assertFalse(result)
    
    @patch('transfer_service.views.EmailMessage')
    @patch('transfer_service.views.render_to_string')
    def test_send_goods_issue_notification_email_failure(self, mock_render, mock_email):
        """Test notification handling when email sending fails"""
        from transfer_service.views import send_goods_issue_notification
        
        mock_render.return_value = '<html>Test email content</html>'
        mock_email_instance = Mock()
        mock_email.return_value = mock_email_instance
        mock_email_instance.send.side_effect = Exception("SMTP error")
        
        result = send_goods_issue_notification(self.goods_issue)
        
        self.assertFalse(result)


class TransferReceiptCreationViewTest(APITestCase):
    """
    Tests for the transfer receipt creation view
    """
    
    def setUp(self):
        """Set up test data"""
        from core_service.models import CustomUser
        
        # Create test user
        self.user = CustomUser.objects.create_user(
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
        
        # Create store authorization for destination store
        StoreAuthorization.objects.create(
            user=self.user,
            store=self.dest_store,
            role='manager'
        )
        
        # Create test sales order
        self.sales_order = SalesOrder.objects.create(
            object_id='SO123456',
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=1000.00,
            order_date='2024-01-01'
        )
        
        # Create sales order line items
        self.so_line_item1 = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id='ITEM001',
            product_id='PROD001',
            product_name='Test Product 1',
            quantity=10.0,
            unit_price=50.0,
            unit_of_measurement='EA'
        )
        
        self.so_line_item2 = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id='ITEM002',
            product_id='PROD002',
            product_name='Test Product 2',
            quantity=5.0,
            unit_price=100.0,
            unit_of_measurement='EA'
        )
        
        # Create goods issue note
        self.goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order,
            source_store=self.source_store,
            created_by=self.user
        )
        
        # Create goods issue line items
        self.gi_line_item1 = GoodsIssueLineItem.objects.create(
            goods_issue=self.goods_issue,
            sales_order_line_item=self.so_line_item1,
            quantity_issued=8.0
        )
        
        self.gi_line_item2 = GoodsIssueLineItem.objects.create(
            goods_issue=self.goods_issue,
            sales_order_line_item=self.so_line_item2,
            quantity_issued=5.0
        )
        
        # Authenticate user
        self.client.force_authenticate(user=self.user)
        
        # URL for transfer receipt creation
        self.url = reverse('create-transfer-receipt')
    
    def test_create_transfer_receipt_success(self):
        """Test successful transfer receipt creation"""
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 8.0,
                    'metadata': {}
                },
                {
                    'goods_issue_line_item': self.gi_line_item2.id,
                    'quantity_received': 5.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.send_transfer_receipt_notification') as mock_notification:
            mock_notification.return_value = True
            
            response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])
        self.assertIn('Transfer receipt TR-', response.data['message'])
        self.assertTrue(response.data['notification_sent'])
        
        # Verify transfer receipt was created
        transfer_receipt = TransferReceiptNote.objects.get(goods_issue=self.goods_issue)
        self.assertEqual(transfer_receipt.destination_store, self.dest_store)
        self.assertEqual(transfer_receipt.created_by, self.user)
        
        # Verify line items were created
        line_items = transfer_receipt.line_items.all()
        self.assertEqual(line_items.count(), 2)
        
        # Verify first line item
        tr_item1 = line_items.get(goods_issue_line_item=self.gi_line_item1)
        self.assertEqual(tr_item1.quantity_received, 8.0)
        
        # Verify second line item
        tr_item2 = line_items.get(goods_issue_line_item=self.gi_line_item2)
        self.assertEqual(tr_item2.quantity_received, 5.0)
    
    def test_create_transfer_receipt_partial_quantities(self):
        """Test transfer receipt creation with partial quantities"""
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 6.0,  # Less than issued (8.0)
                    'metadata': {}
                },
                {
                    'goods_issue_line_item': self.gi_line_item2.id,
                    'quantity_received': 4.0,  # Less than issued (5.0)
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.send_transfer_receipt_notification') as mock_notification:
            mock_notification.return_value = True
            
            response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])
        
        # Verify transfer receipt was created with partial quantities
        transfer_receipt = TransferReceiptNote.objects.get(goods_issue=self.goods_issue)
        line_items = transfer_receipt.line_items.all()
        
        tr_item1 = line_items.get(goods_issue_line_item=self.gi_line_item1)
        self.assertEqual(tr_item1.quantity_received, 6.0)
        
        tr_item2 = line_items.get(goods_issue_line_item=self.gi_line_item2)
        self.assertEqual(tr_item2.quantity_received, 4.0)
    
    def test_create_transfer_receipt_unauthorized_store(self):
        """Test transfer receipt creation fails for unauthorized store"""
        # Create another store without authorization
        unauthorized_store = Store.objects.create(
            store_name='Unauthorized Store',
            icg_warehouse_code='UNAUTH001',
            byd_cost_center_code='CC999'
        )
        
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': unauthorized_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'AUTHORIZATION_ERROR')
        self.assertIn('not authorized', response.data['message'])
    
    def test_create_transfer_receipt_store_mismatch(self):
        """Test transfer receipt creation fails when destination store doesn't match sales order"""
        # Create another store
        wrong_store = Store.objects.create(
            store_name='Wrong Store',
            icg_warehouse_code='WRONG001',
            byd_cost_center_code='CC999'
        )
        
        # Add authorization for wrong store
        StoreAuthorization.objects.create(
            user=self.user,
            store=wrong_store,
            role='manager'
        )
        
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': wrong_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'STORE_MISMATCH')
        self.assertIn('must match the sales order destination store', response.data['message'])
    
    def test_create_transfer_receipt_quantity_exceeded(self):
        """Test transfer receipt creation fails when received quantity exceeds issued quantity"""
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 10.0,  # More than issued (8.0)
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'QUANTITY_EXCEEDED')
        self.assertIn('Cannot receive 10.0', response.data['message'])
        self.assertIn('Available: 8.0', response.data['message'])
    
    def test_create_transfer_receipt_line_item_mismatch(self):
        """Test transfer receipt creation fails when line item doesn't belong to goods issue"""
        # Create another goods issue
        other_goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order,
            source_store=self.source_store,
            created_by=self.user
        )
        
        other_gi_line_item = GoodsIssueLineItem.objects.create(
            goods_issue=other_goods_issue,
            sales_order_line_item=self.so_line_item1,
            quantity_issued=5.0
        )
        
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': other_gi_line_item.id,  # Wrong goods issue
                    'quantity_received': 5.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'LINE_ITEM_MISMATCH')
        self.assertIn('does not belong to goods issue', response.data['message'])
    
    def test_create_transfer_receipt_validation_error(self):
        """Test transfer receipt creation with invalid data"""
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': -5.0,  # Invalid negative quantity
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')
    
    def test_create_transfer_receipt_missing_line_items(self):
        """Test transfer receipt creation fails without line items"""
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [],  # Empty line items
            'metadata': {}
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'VALIDATION_ERROR')
    
    def test_create_transfer_receipt_unauthenticated(self):
        """Test transfer receipt creation fails for unauthenticated user"""
        self.client.force_authenticate(user=None)
        
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    @patch('transfer_service.models.TransferReceiptNote.update_destination_inventory')
    @patch('transfer_service.models.TransferReceiptNote.complete_transfer_in_sap')
    def test_create_transfer_receipt_triggers_async_tasks(self, mock_complete_sap, mock_update_inventory):
        """Test that transfer receipt creation triggers async tasks"""
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 8.0,
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.send_transfer_receipt_notification') as mock_notification:
            mock_notification.return_value = True
            
            response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify async tasks were triggered
        mock_update_inventory.assert_called_once()
        mock_complete_sap.assert_called_once()
    
    def test_create_transfer_receipt_multiple_receipts_same_goods_issue(self):
        """Test creating multiple transfer receipts for the same goods issue (partial receipts)"""
        # First receipt - partial quantities
        data1 = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 5.0,  # Partial of 8.0 issued
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.send_transfer_receipt_notification') as mock_notification:
            mock_notification.return_value = True
            
            response1 = self.client.post(self.url, data1, format='json')
        
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        
        # Second receipt - remaining quantities
        data2 = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 3.0,  # Remaining 3.0 of 8.0 issued
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        with patch('transfer_service.views.send_transfer_receipt_notification') as mock_notification:
            mock_notification.return_value = True
            
            response2 = self.client.post(self.url, data2, format='json')
        
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
        
        # Verify both receipts exist
        receipts = TransferReceiptNote.objects.filter(goods_issue=self.goods_issue)
        self.assertEqual(receipts.count(), 2)
        
        # Verify total received quantity
        total_received = sum(
            item.quantity_received 
            for receipt in receipts 
            for item in receipt.line_items.filter(goods_issue_line_item=self.gi_line_item1)
        )
        self.assertEqual(total_received, 8.0)
    
    def test_create_transfer_receipt_exceeds_total_with_existing_receipts(self):
        """Test that creating a receipt fails when total would exceed issued quantity"""
        # Create first receipt
        first_receipt = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        TransferReceiptLineItem.objects.create(
            transfer_receipt=first_receipt,
            goods_issue_line_item=self.gi_line_item1,
            quantity_received=6.0  # 6.0 of 8.0 issued
        )
        
        # Try to create second receipt that would exceed total
        data = {
            'goods_issue': self.goods_issue.id,
            'destination_store': self.dest_store.id,
            'line_items': [
                {
                    'goods_issue_line_item': self.gi_line_item1.id,
                    'quantity_received': 4.0,  # Would total 10.0, exceeding 8.0 issued
                    'metadata': {}
                }
            ],
            'metadata': {}
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'QUANTITY_EXCEEDED')
        self.assertIn('Available: 2.0', response.data['message'])


class TransferReceiptNotificationTest(TestCase):
    """
    Tests for transfer receipt email notification functionality
    """
    
    def setUp(self):
        """Set up test data"""
        from core_service.models import CustomUser
        
        # Create test users
        self.user = CustomUser.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.source_manager = CustomUser.objects.create_user(
            username='sourcemanager',
            email='source@example.com',
            password='testpass123'
        )
        
        self.dest_manager = CustomUser.objects.create_user(
            username='destmanager',
            email='dest@example.com',
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
        
        # Create store authorizations
        StoreAuthorization.objects.create(
            user=self.source_manager,
            store=self.source_store,
            role='manager'
        )
        
        StoreAuthorization.objects.create(
            user=self.dest_manager,
            store=self.dest_store,
            role='manager'
        )
        
        # Create test sales order
        self.sales_order = SalesOrder.objects.create(
            object_id='SO123456',
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=1000.00,
            order_date='2024-01-01'
        )
        
        # Create sales order line item
        self.so_line_item = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id='ITEM001',
            product_id='PROD001',
            product_name='Test Product 1',
            quantity=10.0,
            unit_price=50.0,
            unit_of_measurement='EA'
        )
        
        # Create goods issue
        self.goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order,
            source_store=self.source_store,
            created_by=self.user
        )
        
        # Create goods issue line item
        self.gi_line_item = GoodsIssueLineItem.objects.create(
            goods_issue=self.goods_issue,
            sales_order_line_item=self.so_line_item,
            quantity_issued=8.0
        )
        
        # Create transfer receipt
        self.transfer_receipt = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        # Create transfer receipt line item
        self.tr_line_item = TransferReceiptLineItem.objects.create(
            transfer_receipt=self.transfer_receipt,
            goods_issue_line_item=self.gi_line_item,
            quantity_received=8.0
        )
    
    @patch('transfer_service.views.EmailMessage')
    @patch('transfer_service.views.render_to_string')
    def test_send_transfer_receipt_notification_success(self, mock_render, mock_email):
        """Test successful transfer receipt notification sending"""
        from transfer_service.views import send_transfer_receipt_notification
        
        # Mock template rendering
        mock_render.return_value = '<html>Test email content</html>'
        
        # Mock email sending
        mock_email_instance = Mock()
        mock_email.return_value = mock_email_instance
        
        result = send_transfer_receipt_notification(self.transfer_receipt)
        
        self.assertTrue(result)
        
        # Verify templates were rendered
        self.assertEqual(mock_render.call_count, 2)  # Completion and receipt notifications
        
        # Verify emails were created and sent
        self.assertEqual(mock_email.call_count, 2)
        mock_email_instance.send.assert_called()
    
    @patch('transfer_service.views.EmailMessage')
    @patch('transfer_service.views.render_to_string')
    def test_send_transfer_receipt_notification_with_variations(self, mock_render, mock_email):
        """Test transfer receipt notification with quantity variations"""
        from transfer_service.views import send_transfer_receipt_notification
        
        # Update receipt to have quantity variation
        self.tr_line_item.quantity_received = 6.0  # Less than issued (8.0)
        self.tr_line_item.save()
        
        # Mock template rendering
        mock_render.return_value = '<html>Test email content</html>'
        
        # Mock email sending
        mock_email_instance = Mock()
        mock_email.return_value = mock_email_instance
        
        result = send_transfer_receipt_notification(self.transfer_receipt)
        
        self.assertTrue(result)
        
        # Verify variation notification was also sent (3 total emails)
        self.assertEqual(mock_render.call_count, 3)
        self.assertEqual(mock_email.call_count, 3)
    
    @patch('transfer_service.views.EmailMessage')
    def test_send_transfer_receipt_notification_no_managers(self, mock_email):
        """Test notification handling when no store managers exist"""
        from transfer_service.views import send_transfer_receipt_notification
        
        # Remove all store authorizations
        StoreAuthorization.objects.all().delete()
        
        result = send_transfer_receipt_notification(self.transfer_receipt)
        
        # Should still return True but no emails sent
        self.assertTrue(result)
        mock_email.assert_not_called()
    
    @patch('transfer_service.views.EmailMessage')
    def test_send_transfer_receipt_notification_no_email_addresses(self, mock_email):
        """Test notification handling when managers have no email addresses"""
        from transfer_service.views import send_transfer_receipt_notification
        
        # Remove email addresses from managers
        self.source_manager.email = ''
        self.source_manager.save()
        self.dest_manager.email = ''
        self.dest_manager.save()
        
        result = send_transfer_receipt_notification(self.transfer_receipt)
        
        # Should still return True but no emails sent
        self.assertTrue(result)
        mock_email.assert_not_called()
    
    @patch('transfer_service.views.EmailMessage')
    @patch('transfer_service.views.render_to_string')
    def test_send_transfer_receipt_notification_email_failure(self, mock_render, mock_email):
        """Test notification handling when email sending fails"""
        from transfer_service.views import send_transfer_receipt_notification
        
        # Mock template rendering
        mock_render.return_value = '<html>Test email content</html>'
        
        # Mock email sending failure
        mock_email_instance = Mock()
        mock_email_instance.send.side_effect = Exception("Email sending failed")
        mock_email.return_value = mock_email_instance
        
        result = send_transfer_receipt_notification(self.transfer_receipt)
        
        # Should return False when email sending fails
        self.assertFalse(result)


class TransferReceiptModelTest(TestCase):
    """
    Tests for TransferReceiptNote and TransferReceiptLineItem models
    """
    
    def setUp(self):
        """Set up test data"""
        from core_service.models import CustomUser
        
        # Create test user
        self.user = CustomUser.objects.create_user(
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
        
        # Create test sales order
        self.sales_order = SalesOrder.objects.create(
            object_id='SO123456',
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=1000.00,
            order_date='2024-01-01'
        )
        
        # Create sales order line item
        self.so_line_item = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id='ITEM001',
            product_id='PROD001',
            product_name='Test Product 1',
            quantity=10.0,
            unit_price=50.0,
            unit_of_measurement='EA'
        )
        
        # Create goods issue
        self.goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order,
            source_store=self.source_store,
            created_by=self.user
        )
        
        # Create goods issue line item
        self.gi_line_item = GoodsIssueLineItem.objects.create(
            goods_issue=self.goods_issue,
            sales_order_line_item=self.so_line_item,
            quantity_issued=8.0
        )
    
    def test_transfer_receipt_creation_and_properties(self):
        """Test transfer receipt creation and calculated properties"""
        transfer_receipt = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        # Create line item
        tr_line_item = TransferReceiptLineItem.objects.create(
            transfer_receipt=transfer_receipt,
            goods_issue_line_item=self.gi_line_item,
            quantity_received=7.0
        )
        
        # Test properties
        self.assertEqual(transfer_receipt.total_quantity_received, 7.0)
        self.assertEqual(transfer_receipt.total_value_received, 350.0)  # 7.0 * 50.0
        self.assertEqual(str(transfer_receipt), f'TR-{transfer_receipt.receipt_number}')
        
        # Test line item properties
        self.assertEqual(tr_line_item.value_received, 350.0)
        self.assertEqual(tr_line_item.product_name, 'Test Product 1')
        self.assertEqual(tr_line_item.product_id, 'PROD001')
    
    def test_transfer_receipt_line_item_validation(self):
        """Test transfer receipt line item validation"""
        transfer_receipt = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        # Test quantity validation - exceeds issued quantity
        tr_line_item = TransferReceiptLineItem(
            transfer_receipt=transfer_receipt,
            goods_issue_line_item=self.gi_line_item,
            quantity_received=10.0  # More than issued (8.0)
        )
        
        with self.assertRaises(ValidationError) as context:
            tr_line_item.clean()
        
        self.assertIn('Cannot receive 10.0', str(context.exception))
        self.assertIn('Available quantity: 8.0', str(context.exception))
    
    def test_transfer_receipt_line_item_validation_with_existing_receipts(self):
        """Test line item validation considers existing receipts"""
        transfer_receipt1 = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        # Create first receipt for 5.0
        TransferReceiptLineItem.objects.create(
            transfer_receipt=transfer_receipt1,
            goods_issue_line_item=self.gi_line_item,
            quantity_received=5.0
        )
        
        transfer_receipt2 = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        # Try to create second receipt for 5.0 (would total 10.0, exceeding 8.0 issued)
        tr_line_item2 = TransferReceiptLineItem(
            transfer_receipt=transfer_receipt2,
            goods_issue_line_item=self.gi_line_item,
            quantity_received=5.0
        )
        
        with self.assertRaises(ValidationError) as context:
            tr_line_item2.clean()
        
        self.assertIn('Cannot receive 5.0', str(context.exception))
        self.assertIn('Available quantity: 3.0', str(context.exception))
    
    @patch('django_q.tasks.async_task')
    def test_transfer_receipt_async_task_methods(self, mock_async_task):
        """Test that transfer receipt methods trigger async tasks"""
        transfer_receipt = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        # Test update_destination_inventory
        transfer_receipt.update_destination_inventory()
        mock_async_task.assert_called_with(
            'transfer_service.tasks.update_transfer_receipt_inventory',
            transfer_receipt.id
        )
        
        # Test complete_transfer_in_sap
        transfer_receipt.complete_transfer_in_sap()
        mock_async_task.assert_called_with(
            'transfer_service.tasks.update_sales_order_status',
            self.sales_order.id
        )
    
    def test_transfer_receipt_number_generation(self):
        """Test that transfer receipt numbers are generated correctly"""
        transfer_receipt = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        # Receipt number should be based on goods issue number
        expected_base = int(str(self.goods_issue.issue_number) + '1')
        self.assertEqual(transfer_receipt.receipt_number, expected_base)
    
    def test_transfer_receipt_number_uniqueness(self):
        """Test that transfer receipt numbers are unique"""
        # Create first receipt
        receipt1 = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        # Create second receipt - should get incremented number
        receipt2 = TransferReceiptNote.objects.create(
            goods_issue=self.goods_issue,
            destination_store=self.dest_store,
            created_by=self.user
        )
        
        self.assertNotEqual(receipt1.receipt_number, receipt2.receipt_number)
        self.assertEqual(receipt2.receipt_number, receipt1.receipt_number + 1)