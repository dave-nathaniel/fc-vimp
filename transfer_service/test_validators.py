"""
Unit tests for transfer service validators
"""
import unittest
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from unittest.mock import Mock, patch

from .validators import (
    FieldValidator, TransferDataValidator, SalesOrderValidator,
    GoodsIssueValidator, TransferReceiptValidator, StoreAuthorizationValidator,
    ValidationErrorResponse
)
from .models import SalesOrder, SalesOrderLineItem, GoodsIssueNote, GoodsIssueLineItem, StoreAuthorization
from egrn_service.models import Store
from core_service.models import CustomUser


class FieldValidatorTest(TestCase):
    """Test FieldValidator utility methods"""
    
    def test_validate_required_field_success(self):
        """Test successful required field validation"""
        result = FieldValidator.validate_required_field("test_value", "test_field")
        self.assertEqual(result, "test_value")
    
    def test_validate_required_field_null(self):
        """Test required field validation with null value"""
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_required_field(None, "test_field")
        
        self.assertIn("test_field", context.exception.error_dict)
        self.assertIn("is required", str(context.exception.error_dict["test_field"][0]))
    
    def test_validate_required_field_empty_string(self):
        """Test required field validation with empty string"""
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_required_field("", "test_field")
        
        self.assertIn("test_field", context.exception.error_dict)
        self.assertIn("cannot be empty", str(context.exception.error_dict["test_field"][0]))
    
    def test_validate_positive_decimal_success(self):
        """Test successful positive decimal validation"""
        result = FieldValidator.validate_positive_decimal("123.45", "test_field")
        self.assertEqual(result, Decimal("123.45"))
    
    def test_validate_positive_decimal_negative(self):
        """Test positive decimal validation with negative value"""
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_positive_decimal("-123.45", "test_field")
        
        self.assertIn("test_field", context.exception.error_dict)
        self.assertIn("must be greater than 0", str(context.exception.error_dict["test_field"][0]))
    
    def test_validate_positive_decimal_invalid_format(self):
        """Test positive decimal validation with invalid format"""
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_positive_decimal("invalid", "test_field")
        
        self.assertIn("test_field", context.exception.error_dict)
        self.assertIn("must be a valid decimal number", str(context.exception.error_dict["test_field"][0]))
    
    def test_validate_positive_decimal_too_many_decimal_places(self):
        """Test positive decimal validation with too many decimal places"""
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_positive_decimal("123.12345", "test_field", decimal_places=3)
        
        self.assertIn("test_field", context.exception.error_dict)
        self.assertIn("cannot have more than 3 decimal places", str(context.exception.error_dict["test_field"][0]))
    
    def test_validate_positive_integer_success(self):
        """Test successful positive integer validation"""
        result = FieldValidator.validate_positive_integer("123", "test_field")
        self.assertEqual(result, 123)
    
    def test_validate_positive_integer_negative(self):
        """Test positive integer validation with negative value"""
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_positive_integer("-123", "test_field")
        
        self.assertIn("test_field", context.exception.error_dict)
        self.assertIn("must be greater than 0", str(context.exception.error_dict["test_field"][0]))
    
    def test_validate_string_length_success(self):
        """Test successful string length validation"""
        result = FieldValidator.validate_string_length("test", "test_field", min_length=2, max_length=10)
        self.assertEqual(result, "test")
    
    def test_validate_string_length_too_short(self):
        """Test string length validation with too short value"""
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_string_length("a", "test_field", min_length=2)
        
        self.assertIn("test_field", context.exception.error_dict)
        self.assertIn("must be at least 2 characters", str(context.exception.error_dict["test_field"][0]))
    
    def test_validate_string_length_too_long(self):
        """Test string length validation with too long value"""
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_string_length("toolongstring", "test_field", max_length=5)
        
        self.assertIn("test_field", context.exception.error_dict)
        self.assertIn("cannot be longer than 5 characters", str(context.exception.error_dict["test_field"][0]))
    
    def test_validate_choice_field_success(self):
        """Test successful choice field validation"""
        choices = [('option1', 'Option 1'), ('option2', 'Option 2')]
        result = FieldValidator.validate_choice_field("option1", "test_field", choices)
        self.assertEqual(result, "option1")
    
    def test_validate_choice_field_invalid(self):
        """Test choice field validation with invalid choice"""
        choices = [('option1', 'Option 1'), ('option2', 'Option 2')]
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_choice_field("invalid", "test_field", choices)
        
        self.assertIn("test_field", context.exception.error_dict)
        self.assertIn("must be one of", str(context.exception.error_dict["test_field"][0]))
    
    def test_validate_email_field_success(self):
        """Test successful email validation"""
        result = FieldValidator.validate_email_field("test@example.com", "email_field")
        self.assertEqual(result, "test@example.com")
    
    def test_validate_email_field_invalid(self):
        """Test email validation with invalid format"""
        with self.assertRaises(ValidationError) as context:
            FieldValidator.validate_email_field("invalid-email", "email_field")
        
        self.assertIn("email_field", context.exception.error_dict)
        self.assertIn("must be a valid email address", str(context.exception.error_dict["email_field"][0]))


class SalesOrderValidatorTest(TestCase):
    """Test SalesOrderValidator methods"""
    
    def setUp(self):
        """Set up test data"""
        self.valid_so_data = {
            "ObjectID": "SO123456789",
            "ID": "12345",
            "TotalNetAmount": "1000.50",
            "SellerParty": {"PartyID": "STORE001"},
            "BuyerParty": {"PartyID": "STORE002"},
            "Item": [
                {
                    "ObjectID": "ITEM001",
                    "ProductID": "PROD001",
                    "Description": "Test Product",
                    "Quantity": "10.0",
                    "ListUnitPriceAmount": "100.05",
                    "QuantityUnitCodeText": "EA"
                }
            ]
        }
    
    def test_validate_sales_order_data_success(self):
        """Test successful sales order validation"""
        result = SalesOrderValidator.validate_sales_order_data(self.valid_so_data)
        self.assertTrue(result)
    
    def test_validate_sales_order_data_missing_required_field(self):
        """Test sales order validation with missing required field"""
        invalid_data = self.valid_so_data.copy()
        del invalid_data["ObjectID"]
        
        with self.assertRaises(ValidationError) as context:
            SalesOrderValidator.validate_sales_order_data(invalid_data)
        
        self.assertIn("ObjectID", context.exception.error_dict)
    
    def test_validate_sales_order_data_invalid_id(self):
        """Test sales order validation with invalid ID"""
        invalid_data = self.valid_so_data.copy()
        invalid_data["ID"] = "invalid"
        
        with self.assertRaises(ValidationError) as context:
            SalesOrderValidator.validate_sales_order_data(invalid_data)
        
        self.assertIn("ID", context.exception.error_dict)
    
    def test_validate_sales_order_data_negative_amount(self):
        """Test sales order validation with negative amount"""
        invalid_data = self.valid_so_data.copy()
        invalid_data["TotalNetAmount"] = "-100.0"
        
        with self.assertRaises(ValidationError) as context:
            SalesOrderValidator.validate_sales_order_data(invalid_data)
        
        self.assertIn("TotalNetAmount", context.exception.error_dict)
    
    def test_validate_sales_order_data_missing_seller_party(self):
        """Test sales order validation with missing seller party"""
        invalid_data = self.valid_so_data.copy()
        invalid_data["SellerParty"] = {}
        
        with self.assertRaises(ValidationError) as context:
            SalesOrderValidator.validate_sales_order_data(invalid_data)
        
        self.assertIn("SellerParty", context.exception.error_dict)
    
    def test_validate_sales_order_data_no_items(self):
        """Test sales order validation with no items"""
        invalid_data = self.valid_so_data.copy()
        invalid_data["Item"] = []
        
        with self.assertRaises(ValidationError) as context:
            SalesOrderValidator.validate_sales_order_data(invalid_data)
        
        self.assertIn("Sales order must contain at least one line item", context.exception.error_list)
    
    def test_validate_line_item_data_success(self):
        """Test successful line item validation"""
        item_data = self.valid_so_data["Item"][0]
        result = SalesOrderValidator.validate_line_item_data(item_data, 1)
        self.assertTrue(result)
    
    def test_validate_line_item_data_missing_required_field(self):
        """Test line item validation with missing required field"""
        item_data = self.valid_so_data["Item"][0].copy()
        del item_data["ProductID"]
        
        with self.assertRaises(ValidationError) as context:
            SalesOrderValidator.validate_line_item_data(item_data, 1)
        
        self.assertIn("ProductID", context.exception.error_dict)
    
    def test_validate_line_item_data_invalid_quantity(self):
        """Test line item validation with invalid quantity"""
        item_data = self.valid_so_data["Item"][0].copy()
        item_data["Quantity"] = "invalid"
        
        with self.assertRaises(ValidationError) as context:
            SalesOrderValidator.validate_line_item_data(item_data, 1)
        
        self.assertIn("Quantity", context.exception.error_dict)


class ValidationErrorResponseTest(TestCase):
    """Test ValidationErrorResponse utility methods"""
    
    def test_create_error_response(self):
        """Test creating standard error response"""
        response = ValidationErrorResponse.create_error_response(
            "Test error message",
            "TEST_ERROR",
            field_errors={"field1": ["Error 1"]},
            validation_errors=["General error"]
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['message'], "Test error message")
        self.assertEqual(response.data['error_code'], "TEST_ERROR")
        self.assertIn("field1", response.data['details']['field_errors'])
        self.assertIn("General error", response.data['details']['validation_errors'])
    
    def test_create_validation_error_response_from_django_error(self):
        """Test creating error response from Django ValidationError"""
        django_error = ValidationError("Test validation error")
        response = ValidationErrorResponse.create_validation_error_response(django_error)
        
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], "VALIDATION_ERROR")
    
    def test_create_authorization_error_response(self):
        """Test creating authorization error response"""
        response = ValidationErrorResponse.create_authorization_error_response()
        
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], "AUTHORIZATION_ERROR")
    
    def test_create_not_found_error_response(self):
        """Test creating not found error response"""
        response = ValidationErrorResponse.create_not_found_error_response("Sales Order")
        
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], "NOT_FOUND_ERROR")
        self.assertIn("Sales Order not found", response.data['message'])
    
    def test_create_business_rule_error_response(self):
        """Test creating business rule error response"""
        response = ValidationErrorResponse.create_business_rule_error_response(
            "Business rule violated",
            ["Specific rule violation"]
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], "BUSINESS_RULE_ERROR")
        self.assertIn("Specific rule violation", response.data['details']['validation_errors'])
    
    def test_create_external_system_error_response(self):
        """Test creating external system error response"""
        response = ValidationErrorResponse.create_external_system_error_response(
            "SAP ByD",
            "Connection timeout"
        )
        
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], "EXTERNAL_SYSTEM_ERROR")
        self.assertIn("SAP ByD", response.data['message'])
        self.assertIn("Connection timeout", response.data['details']['validation_errors'])
    
    def test_create_internal_error_response(self):
        """Test creating internal error response"""
        response = ValidationErrorResponse.create_internal_error_response("Database error")
        
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], "INTERNAL_ERROR")
        self.assertIn("Database error", response.data['details']['validation_errors'])


class GoodsIssueValidatorTest(TestCase):
    """Test GoodsIssueValidator methods"""
    
    def setUp(self):
        """Set up test data"""
        # Create test stores with unique identifiers
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        
        self.source_store = Store.objects.create(
            store_name=f"Source Store {unique_id}",
            byd_cost_center_code=f"SRC{unique_id}",
            icg_warehouse_code=f"SRC_WH_{unique_id}"
        )
        self.dest_store = Store.objects.create(
            store_name=f"Destination Store {unique_id}",
            byd_cost_center_code=f"DST{unique_id}",
            icg_warehouse_code=f"DST_WH_{unique_id}"
        )
        
        # Create test user
        self.user = CustomUser.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        
        # Create test sales order
        self.sales_order = SalesOrder.objects.create(
            object_id="SO123",
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=Decimal("1000.00"),
            order_date="2024-01-01"
        )
        
        # Create test line item
        self.line_item = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id="ITEM001",
            product_id="PROD001",
            product_name="Test Product",
            quantity=Decimal("10.0"),
            unit_price=Decimal("100.0"),
            unit_of_measurement="EA"
        )
    
    def test_validate_goods_issue_creation_success(self):
        """Test successful goods issue creation validation"""
        line_items_data = [
            {
                'sales_order_line_item': self.line_item,
                'quantity_issued': Decimal("5.0"),
                'metadata': {}
            }
        ]
        
        result = GoodsIssueValidator.validate_goods_issue_creation(
            self.sales_order,
            self.source_store,
            line_items_data,
            self.user
        )
        self.assertTrue(result)
    
    def test_validate_goods_issue_creation_wrong_store(self):
        """Test goods issue creation validation with wrong store"""
        line_items_data = [
            {
                'sales_order_line_item': self.line_item,
                'quantity_issued': Decimal("5.0")
            }
        ]
        
        with self.assertRaises(ValidationError) as context:
            GoodsIssueValidator.validate_goods_issue_creation(
                self.sales_order,
                self.dest_store,  # Wrong store
                line_items_data,
                self.user
            )
        
        self.assertIn("does not match", str(context.exception.error_list[0]))
    
    def test_validate_goods_issue_creation_no_line_items(self):
        """Test goods issue creation validation with no line items"""
        with self.assertRaises(ValidationError) as context:
            GoodsIssueValidator.validate_goods_issue_creation(
                self.sales_order,
                self.source_store,
                [],  # No line items
                self.user
            )
        
        self.assertIn("At least one line item is required", context.exception.error_list)
    
    def test_validate_goods_issue_line_item_success(self):
        """Test successful goods issue line item validation"""
        item_data = {
            'sales_order_line_item': self.line_item,
            'quantity_issued': Decimal("5.0"),
            'metadata': {}
        }
        
        result = GoodsIssueValidator.validate_goods_issue_line_item(
            item_data,
            self.sales_order,
            1
        )
        self.assertTrue(result)
    
    def test_validate_goods_issue_line_item_excessive_quantity(self):
        """Test goods issue line item validation with excessive quantity"""
        item_data = {
            'sales_order_line_item': self.line_item,
            'quantity_issued': Decimal("15.0"),  # More than available (10.0)
            'metadata': {}
        }
        
        with self.assertRaises(ValidationError) as context:
            GoodsIssueValidator.validate_goods_issue_line_item(
                item_data,
                self.sales_order,
                1
            )
        
        self.assertIn("Cannot issue", str(context.exception.error_list[0]))


class TransferReceiptValidatorTest(TestCase):
    """Test TransferReceiptValidator methods"""
    
    def setUp(self):
        """Set up test data"""
        # Create test stores with unique identifiers
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        
        self.source_store = Store.objects.create(
            store_name=f"Source Store {unique_id}",
            byd_cost_center_code=f"SRC{unique_id}",
            icg_warehouse_code=f"SRC_WH_{unique_id}"
        )
        self.dest_store = Store.objects.create(
            store_name=f"Destination Store {unique_id}",
            byd_cost_center_code=f"DST{unique_id}",
            icg_warehouse_code=f"DST_WH_{unique_id}"
        )
        
        # Create test user
        self.user = CustomUser.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        
        # Create test sales order
        self.sales_order = SalesOrder.objects.create(
            object_id="SO123",
            sales_order_id=12345,
            source_store=self.source_store,
            destination_store=self.dest_store,
            total_net_amount=Decimal("1000.00"),
            order_date="2024-01-01"
        )
        
        # Create test line item
        self.line_item = SalesOrderLineItem.objects.create(
            sales_order=self.sales_order,
            object_id="ITEM001",
            product_id="PROD001",
            product_name="Test Product",
            quantity=Decimal("10.0"),
            unit_price=Decimal("100.0"),
            unit_of_measurement="EA"
        )
        
        # Create test goods issue
        self.goods_issue = GoodsIssueNote.objects.create(
            sales_order=self.sales_order,
            issue_number=123451,
            source_store=self.source_store,
            created_by=self.user,
            posted_to_icg=True,
            posted_to_sap=True
        )
        
        # Create test goods issue line item
        self.gi_line_item = GoodsIssueLineItem.objects.create(
            goods_issue=self.goods_issue,
            sales_order_line_item=self.line_item,
            quantity_issued=Decimal("8.0")
        )
    
    def test_validate_transfer_receipt_creation_success(self):
        """Test successful transfer receipt creation validation"""
        line_items_data = [
            {
                'goods_issue_line_item': self.gi_line_item,
                'quantity_received': Decimal("8.0"),
                'metadata': {}
            }
        ]
        
        result = TransferReceiptValidator.validate_transfer_receipt_creation(
            self.goods_issue,
            self.dest_store,
            line_items_data,
            self.user
        )
        self.assertTrue(result)
    
    def test_validate_transfer_receipt_creation_wrong_store(self):
        """Test transfer receipt creation validation with wrong store"""
        line_items_data = [
            {
                'goods_issue_line_item': self.gi_line_item,
                'quantity_received': Decimal("8.0")
            }
        ]
        
        with self.assertRaises(ValidationError) as context:
            TransferReceiptValidator.validate_transfer_receipt_creation(
                self.goods_issue,
                self.source_store,  # Wrong store
                line_items_data,
                self.user
            )
        
        self.assertIn("does not match", str(context.exception.error_list[0]))
    
    def test_validate_transfer_receipt_creation_not_posted_to_icg(self):
        """Test transfer receipt creation validation when goods issue not posted to ICG"""
        self.goods_issue.posted_to_icg = False
        self.goods_issue.save()
        
        line_items_data = [
            {
                'goods_issue_line_item': self.gi_line_item,
                'quantity_received': Decimal("8.0")
            }
        ]
        
        with self.assertRaises(ValidationError) as context:
            TransferReceiptValidator.validate_transfer_receipt_creation(
                self.goods_issue,
                self.dest_store,
                line_items_data,
                self.user
            )
        
        self.assertIn("must be posted to ICG", str(context.exception.error_list[0]))
    
    def test_validate_transfer_receipt_line_item_excessive_quantity(self):
        """Test transfer receipt line item validation with excessive quantity"""
        item_data = {
            'goods_issue_line_item': self.gi_line_item,
            'quantity_received': Decimal("10.0"),  # More than issued (8.0)
            'metadata': {}
        }
        
        with self.assertRaises(ValidationError) as context:
            TransferReceiptValidator.validate_transfer_receipt_line_item(
                item_data,
                self.goods_issue,
                1
            )
        
        self.assertIn("Cannot receive", str(context.exception.error_list[0]))


class StoreAuthorizationValidatorTest(TestCase):
    """Test StoreAuthorizationValidator methods"""
    
    def setUp(self):
        """Set up test data"""
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        
        self.store = Store.objects.create(
            store_name=f"Test Store {unique_id}",
            byd_cost_center_code=f"TST{unique_id}",
            icg_warehouse_code=f"TST_WH_{unique_id}"
        )
        
        self.user = CustomUser.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        
        # Create store authorization
        StoreAuthorization.objects.create(
            user=self.user,
            store=self.store,
            role="manager"
        )
    
    def test_validate_store_access_success(self):
        """Test successful store access validation"""
        result = StoreAuthorizationValidator.validate_store_access(
            self.user,
            self.store.id
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.role, "manager")
    
    def test_validate_store_access_no_authorization(self):
        """Test store access validation with no authorization"""
        unauthorized_user = CustomUser.objects.create_user(
            username="unauthorized",
            email="unauthorized@example.com"
        )
        
        with self.assertRaises(ValidationError) as context:
            StoreAuthorizationValidator.validate_store_access(
                unauthorized_user,
                self.store.id
            )
        
        self.assertIn("is not authorized", str(context.exception))
    
    def test_validate_store_access_insufficient_role(self):
        """Test store access validation with insufficient role"""
        # Create user with viewer role
        viewer_user = CustomUser.objects.create_user(
            username="viewer",
            email="viewer@example.com"
        )
        
        StoreAuthorization.objects.create(
            user=viewer_user,
            store=self.store,
            role="viewer"
        )
        
        with self.assertRaises(ValidationError) as context:
            StoreAuthorizationValidator.validate_store_access(
                viewer_user,
                self.store.id,
                required_roles=["manager", "assistant"]
            )
        
        self.assertIn("does not have required role", str(context.exception))
    
    def test_validate_store_access_unauthenticated_user(self):
        """Test store access validation with unauthenticated user"""
        unauthenticated_user = Mock()
        unauthenticated_user.is_authenticated = False
        
        with self.assertRaises(ValidationError) as context:
            StoreAuthorizationValidator.validate_store_access(
                unauthenticated_user,
                self.store.id
            )
        
        self.assertIn("must be authenticated", str(context.exception.error_list[0]))