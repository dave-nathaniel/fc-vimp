from django.test import TestCase
from django.contrib.auth import get_user_model
from egrn_service.models import Store
from .models import SalesOrder, StoreAuthorization

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