"""
Custom validation classes for transfer service data
"""
from django.core.exceptions import ValidationError
from django.db.models import Sum
from decimal import Decimal, InvalidOperation
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework import status
import logging
from egrn_service.models import Store
from .models import StoreAuthorization

logger = logging.getLogger(__name__)


class ValidationErrorResponse:
    """
    Utility class for creating standardized error responses
    """
    
    @staticmethod
    def create_error_response(message, error_code, field_errors=None, validation_errors=None, status_code=status.HTTP_400_BAD_REQUEST):
        """
        Create a standardized error response
        """
        return Response({
            'success': False,
            'message': message,
            'error_code': error_code,
            'details': {
                'field_errors': field_errors or {},
                'validation_errors': validation_errors or []
            }
        }, status=status_code)
    
    @staticmethod
    def create_validation_error_response(errors):
        """
        Create error response from Django ValidationError or DRF serializer errors
        """
        if isinstance(errors, ValidationError):
            if hasattr(errors, 'error_dict'):
                # Field-specific errors
                field_errors = {}
                validation_errors = []
                for field, error_list in errors.error_dict.items():
                    field_errors[field] = [str(error) for error in error_list]
                return ValidationErrorResponse.create_error_response(
                    'Validation failed',
                    'VALIDATION_ERROR',
                    field_errors=field_errors,
                    validation_errors=validation_errors
                )
            else:
                # General validation errors
                validation_errors = [str(error) for error in errors.error_list] if hasattr(errors, 'error_list') else [str(errors)]
                return ValidationErrorResponse.create_error_response(
                    'Validation failed',
                    'VALIDATION_ERROR',
                    validation_errors=validation_errors
                )
        elif isinstance(errors, dict):
            # DRF serializer errors
            field_errors = {}
            validation_errors = []
            for field, error_list in errors.items():
                if field == 'non_field_errors':
                    validation_errors.extend([str(error) for error in error_list])
                else:
                    field_errors[field] = [str(error) for error in error_list]
            return ValidationErrorResponse.create_error_response(
                'Validation failed',
                'VALIDATION_ERROR',
                field_errors=field_errors,
                validation_errors=validation_errors
            )
        else:
            # Generic error
            return ValidationErrorResponse.create_error_response(
                'Validation failed',
                'VALIDATION_ERROR',
                validation_errors=[str(errors)]
            )
    
    @staticmethod
    def create_authorization_error_response(message="You are not authorized to perform this action"):
        """
        Create authorization error response
        """
        return ValidationErrorResponse.create_error_response(
            message,
            'AUTHORIZATION_ERROR',
            status_code=status.HTTP_403_FORBIDDEN
        )
    
    @staticmethod
    def create_not_found_error_response(resource_name="Resource"):
        """
        Create not found error response
        """
        return ValidationErrorResponse.create_error_response(
            f'{resource_name} not found',
            'NOT_FOUND_ERROR',
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    @staticmethod
    def create_business_rule_error_response(message, validation_errors=None):
        """
        Create business rule violation error response
        """
        return ValidationErrorResponse.create_error_response(
            message,
            'BUSINESS_RULE_ERROR',
            validation_errors=validation_errors or [message]
        )
    
    @staticmethod
    def create_external_system_error_response(system_name, error_message):
        """
        Create external system integration error response
        """
        return ValidationErrorResponse.create_error_response(
            f'Integration with {system_name} failed',
            'EXTERNAL_SYSTEM_ERROR',
            validation_errors=[error_message],
            status_code=status.HTTP_502_BAD_GATEWAY
        )
    
    @staticmethod
    def create_internal_error_response(error_message="An internal error occurred"):
        """
        Create internal server error response
        """
        return ValidationErrorResponse.create_error_response(
            'Internal server error',
            'INTERNAL_ERROR',
            validation_errors=[error_message],
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class FieldValidator:
    """
    Field-level validation utilities
    """
    
    @staticmethod
    def validate_required_field(value, field_name):
        """
        Validate that a required field is not empty
        """
        if value is None:
            raise ValidationError({field_name: [f"{field_name} is required"]})
        
        if isinstance(value, str) and value.strip() == "":
            raise ValidationError({field_name: [f"{field_name} cannot be empty"]})
        
        return value
    
    @staticmethod
    def validate_positive_decimal(value, field_name="value", max_digits=15, decimal_places=3):
        """
        Validate that a decimal value is positive and within limits
        """
        if value is None:
            raise ValidationError({field_name: [f"{field_name} cannot be null"]})
        
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError({field_name: [f"{field_name} must be a valid decimal number"]})
        
        if decimal_value <= 0:
            raise ValidationError({field_name: [f"{field_name} must be greater than 0"]})
        
        # Check decimal places
        if decimal_value.as_tuple().exponent < -decimal_places:
            raise ValidationError({field_name: [f"{field_name} cannot have more than {decimal_places} decimal places"]})
        
        # Check total digits
        total_digits = len(decimal_value.as_tuple().digits)
        if total_digits > max_digits:
            raise ValidationError({field_name: [f"{field_name} cannot have more than {max_digits} total digits"]})
        
        return decimal_value
    
    @staticmethod
    def validate_positive_integer(value, field_name="value"):
        """
        Validate that an integer value is positive
        """
        if value is None:
            raise ValidationError({field_name: [f"{field_name} cannot be null"]})
        
        try:
            int_value = int(value)
        except (ValueError, TypeError):
            raise ValidationError({field_name: [f"{field_name} must be a valid integer"]})
        
        if int_value <= 0:
            raise ValidationError({field_name: [f"{field_name} must be greater than 0"]})
        
        return int_value
    
    @staticmethod
    def validate_string_length(value, field_name, min_length=None, max_length=None):
        """
        Validate string length constraints
        """
        if value is None:
            raise ValidationError({field_name: [f"{field_name} cannot be null"]})
        
        if not isinstance(value, str):
            raise ValidationError({field_name: [f"{field_name} must be a string"]})
        
        if min_length is not None and len(value) < min_length:
            raise ValidationError({field_name: [f"{field_name} must be at least {min_length} characters long"]})
        
        if max_length is not None and len(value) > max_length:
            raise ValidationError({field_name: [f"{field_name} cannot be longer than {max_length} characters"]})
        
        return value
    
    @staticmethod
    def validate_choice_field(value, field_name, choices):
        """
        Validate that value is in allowed choices
        """
        if value is None:
            raise ValidationError({field_name: [f"{field_name} cannot be null"]})
        
        valid_choices = [choice[0] for choice in choices] if isinstance(choices[0], (list, tuple)) else choices
        
        if value not in valid_choices:
            raise ValidationError({field_name: [f"{field_name} must be one of: {', '.join(valid_choices)}"]})
        
        return value
    
    @staticmethod
    def validate_email_field(value, field_name):
        """
        Validate email format
        """
        if value is None:
            return value  # Allow null emails
        
        if not isinstance(value, str):
            raise ValidationError({field_name: [f"{field_name} must be a string"]})
        
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, value):
            raise ValidationError({field_name: [f"{field_name} must be a valid email address"]})
        
        return value
    
    @staticmethod
    def validate_date_field(value, field_name):
        """
        Validate date field
        """
        if value is None:
            raise ValidationError({field_name: [f"{field_name} cannot be null"]})
        
        from datetime import date, datetime
        
        if isinstance(value, str):
            try:
                from django.utils.dateparse import parse_date
                parsed_date = parse_date(value)
                if parsed_date is None:
                    raise ValueError()
                return parsed_date
            except (ValueError, TypeError):
                raise ValidationError({field_name: [f"{field_name} must be a valid date in YYYY-MM-DD format"]})
        elif isinstance(value, datetime):
            return value.date()
        elif isinstance(value, date):
            return value
        else:
            raise ValidationError({field_name: [f"{field_name} must be a valid date"]})


class TransferDataValidator:
    """
    Base validator class for transfer-related data validation
    """
    
    @staticmethod
    def validate_positive_decimal(value, field_name="value"):
        """
        Validate that a decimal value is positive
        """
        return FieldValidator.validate_positive_decimal(value, field_name)
    
    @staticmethod
    def validate_stores_different(source_store, destination_store):
        """
        Validate that source and destination stores are different
        """
        if source_store == destination_store:
            raise ValidationError("Source and destination stores cannot be the same")
        
        return True
    
    @staticmethod
    def validate_required_field(value, field_name):
        """
        Validate that a required field is not empty
        """
        return FieldValidator.validate_required_field(value, field_name)
    
    @staticmethod
    def validate_model_instance(instance, model_class, field_name):
        """
        Validate that instance is of expected model type
        """
        if instance is None:
            raise ValidationError({field_name: [f"{field_name} cannot be null"]})
        
        if not isinstance(instance, model_class):
            raise ValidationError({field_name: [f"{field_name} must be a valid {model_class.__name__} instance"]})
        
        return instance
    
    @staticmethod
    def validate_foreign_key_exists(model_class, field_name, lookup_value, lookup_field='id'):
        """
        Validate that foreign key reference exists
        """
        try:
            lookup_kwargs = {lookup_field: lookup_value}
            instance = model_class.objects.get(**lookup_kwargs)
            return instance
        except model_class.DoesNotExist:
            raise ValidationError({field_name: [f"{model_class.__name__} with {lookup_field}={lookup_value} does not exist"]})
        except Exception as e:
            raise ValidationError({field_name: [f"Error validating {field_name}: {str(e)}"]})
    
    @staticmethod
    def validate_json_field(value, field_name, required_keys=None):
        """
        Validate JSON field structure
        """
        if value is None:
            return {}
        
        if not isinstance(value, dict):
            raise ValidationError({field_name: [f"{field_name} must be a valid JSON object"]})
        
        if required_keys:
            missing_keys = [key for key in required_keys if key not in value]
            if missing_keys:
                raise ValidationError({field_name: [f"{field_name} missing required keys: {', '.join(missing_keys)}"]})
        
        return value


class SalesOrderValidator(TransferDataValidator):
    """
    Validator for sales order data
    """
    
    @classmethod
    def validate_sales_order_data(cls, so_data):
        """
        Validate sales order data from SAP ByD
        """
        field_errors = {}
        validation_errors = []
        
        # Validate input is a dictionary
        if not isinstance(so_data, dict):
            raise ValidationError("Sales order data must be a valid dictionary")
        
        # Required fields validation
        required_fields = ["ObjectID", "ID", "TotalNetAmount"]
        for field in required_fields:
            try:
                cls.validate_required_field(so_data.get(field), field)
            except ValidationError as e:
                field_errors.update(e.error_dict if hasattr(e, 'error_dict') else {field: [str(e)]})
        
        # Validate ObjectID format
        if "ObjectID" in so_data and so_data["ObjectID"]:
            try:
                FieldValidator.validate_string_length(so_data["ObjectID"], "ObjectID", min_length=1, max_length=32)
            except ValidationError as e:
                field_errors.update(e.error_dict)
        
        # Validate sales order ID is numeric
        if "ID" in so_data and so_data["ID"]:
            try:
                FieldValidator.validate_positive_integer(so_data["ID"], "ID")
            except ValidationError as e:
                field_errors.update(e.error_dict)
        
        # Validate total net amount
        if "TotalNetAmount" in so_data and so_data["TotalNetAmount"]:
            try:
                cls.validate_positive_decimal(so_data["TotalNetAmount"], "TotalNetAmount")
            except ValidationError as e:
                field_errors.update(e.error_dict if hasattr(e, 'error_dict') else {"TotalNetAmount": [str(e)]})
        
        # Validate party information
        seller_party = so_data.get("SellerParty", {})
        buyer_party = so_data.get("BuyerParty", {})
        
        if not isinstance(seller_party, dict):
            field_errors["SellerParty"] = ["SellerParty must be a valid object"]
        elif not seller_party.get("PartyID"):
            field_errors["SellerParty"] = ["SellerParty PartyID is required"]
        
        if not isinstance(buyer_party, dict):
            field_errors["BuyerParty"] = ["BuyerParty must be a valid object"]
        elif not buyer_party.get("PartyID"):
            field_errors["BuyerParty"] = ["BuyerParty PartyID is required"]
        
        # Validate line items exist
        items = so_data.get("Item", [])
        if not items:
            validation_errors.append("Sales order must contain at least one line item")
        elif not isinstance(items, list):
            field_errors["Item"] = ["Item must be a list of line items"]
        else:
            # Validate each line item
            for i, item in enumerate(items):
                try:
                    cls.validate_line_item_data(item, i + 1)
                except ValidationError as e:
                    if hasattr(e, 'error_dict'):
                        for field, errors in e.error_dict.items():
                            field_key = f"Item[{i}].{field}"
                            field_errors[field_key] = errors
                    else:
                        validation_errors.append(f"Line item {i + 1}: {str(e)}")
        
        # Raise combined errors if any exist
        if field_errors or validation_errors:
            error = ValidationError("Sales order validation failed")
            error.error_dict = field_errors
            error.error_list = validation_errors
            raise error
        
        return True
    
    @classmethod
    def validate_line_item_data(cls, item_data, line_number):
        """
        Validate sales order line item data
        """
        field_errors = {}
        
        if not isinstance(item_data, dict):
            raise ValidationError(f"Line item {line_number} must be a valid dictionary")
        
        # Required fields for line items
        required_fields = ["ObjectID", "ProductID", "Description", "Quantity", "ListUnitPriceAmount"]
        for field in required_fields:
            try:
                cls.validate_required_field(item_data.get(field), field)
            except ValidationError as e:
                field_errors.update(e.error_dict if hasattr(e, 'error_dict') else {field: [str(e)]})
        
        # Validate ObjectID format
        if "ObjectID" in item_data and item_data["ObjectID"]:
            try:
                FieldValidator.validate_string_length(item_data["ObjectID"], "ObjectID", min_length=1, max_length=32)
            except ValidationError as e:
                field_errors.update(e.error_dict)
        
        # Validate ProductID format
        if "ProductID" in item_data and item_data["ProductID"]:
            try:
                FieldValidator.validate_string_length(item_data["ProductID"], "ProductID", min_length=1, max_length=32)
            except ValidationError as e:
                field_errors.update(e.error_dict)
        
        # Validate Description format
        if "Description" in item_data and item_data["Description"]:
            try:
                FieldValidator.validate_string_length(item_data["Description"], "Description", min_length=1, max_length=100)
            except ValidationError as e:
                field_errors.update(e.error_dict)
        
        # Validate quantity
        if "Quantity" in item_data and item_data["Quantity"]:
            try:
                cls.validate_positive_decimal(item_data["Quantity"], "Quantity")
            except ValidationError as e:
                field_errors.update(e.error_dict if hasattr(e, 'error_dict') else {"Quantity": [str(e)]})
        
        # Validate unit price
        if "ListUnitPriceAmount" in item_data and item_data["ListUnitPriceAmount"]:
            try:
                cls.validate_positive_decimal(item_data["ListUnitPriceAmount"], "ListUnitPriceAmount")
            except ValidationError as e:
                field_errors.update(e.error_dict if hasattr(e, 'error_dict') else {"ListUnitPriceAmount": [str(e)]})
        
        # Validate unit of measurement if present
        if "QuantityUnitCodeText" in item_data and item_data["QuantityUnitCodeText"]:
            try:
                FieldValidator.validate_string_length(item_data["QuantityUnitCodeText"], "QuantityUnitCodeText", max_length=32)
            except ValidationError as e:
                field_errors.update(e.error_dict)
        
        if field_errors:
            error = ValidationError(f"Line item {line_number} validation failed")
            error.error_dict = field_errors
            raise error
        
        return True


class GoodsIssueValidator(TransferDataValidator):
    """
    Validator for goods issue data
    """
    
    @classmethod
    def validate_goods_issue_creation(cls, sales_order, source_store, line_items_data, user):
        """
        Validate goods issue creation data
        """
        field_errors = {}
        validation_errors = []
        
        # Validate input parameters
        try:
            cls.validate_model_instance(sales_order, type(sales_order), "sales_order")
        except ValidationError as e:
            field_errors.update(e.error_dict)
        
        try:
            cls.validate_model_instance(source_store, type(source_store), "source_store")
        except ValidationError as e:
            field_errors.update(e.error_dict)
        
        try:
            cls.validate_model_instance(user, type(user), "user")
        except ValidationError as e:
            field_errors.update(e.error_dict)
        
        # Validate sales order and store relationship
        if sales_order and source_store and source_store != sales_order.source_store:
            validation_errors.append(
                f"Source store '{source_store.store_name}' does not match "
                f"sales order source store '{sales_order.source_store.store_name}'"
            )
        
        # Validate line items
        if not line_items_data:
            validation_errors.append("At least one line item is required")
        elif not isinstance(line_items_data, list):
            field_errors["line_items"] = ["Line items must be a list"]
        else:
            for i, item_data in enumerate(line_items_data):
                try:
                    cls.validate_goods_issue_line_item(item_data, sales_order, i + 1)
                except ValidationError as e:
                    if hasattr(e, 'error_dict'):
                        for field, errors in e.error_dict.items():
                            field_key = f"line_items[{i}].{field}"
                            field_errors[field_key] = errors
                    else:
                        validation_errors.append(f"Line item {i + 1}: {str(e)}")
        
        # Raise combined errors if any exist
        if field_errors or validation_errors:
            error = ValidationError("Goods issue validation failed")
            error.error_dict = field_errors
            error.error_list = validation_errors
            raise error
        
        return True
    
    @classmethod
    def validate_goods_issue_line_item(cls, item_data, sales_order, line_number):
        """
        Validate individual goods issue line item
        """
        field_errors = {}
        validation_errors = []
        
        if not isinstance(item_data, dict):
            raise ValidationError(f"Line item {line_number} must be a valid dictionary")
        
        # Validate required fields
        if 'sales_order_line_item' not in item_data or item_data['sales_order_line_item'] is None:
            field_errors["sales_order_line_item"] = ["sales_order_line_item is required"]
        
        if 'quantity_issued' not in item_data or item_data['quantity_issued'] is None:
            field_errors["quantity_issued"] = ["quantity_issued is required"]
        
        # If basic validation failed, return early
        if field_errors:
            error = ValidationError(f"Line item {line_number} validation failed")
            error.error_dict = field_errors
            raise error
        
        so_line_item = item_data['sales_order_line_item']
        quantity_issued = item_data['quantity_issued']
        
        # Validate line item belongs to sales order
        if sales_order and so_line_item.sales_order != sales_order:
            validation_errors.append("Line item does not belong to the specified sales order")
        
        # Validate quantity issued
        try:
            quantity_issued = cls.validate_positive_decimal(quantity_issued, "quantity_issued")
        except ValidationError as e:
            field_errors.update(e.error_dict if hasattr(e, 'error_dict') else {"quantity_issued": [str(e)]})
        
        # Validate quantity doesn't exceed available quantity
        if not field_errors and not validation_errors:
            try:
                existing_issued = so_line_item.goods_issue_items.aggregate(
                    total=Sum('quantity_issued')
                )['total'] or Decimal('0')
                
                available_quantity = Decimal(str(so_line_item.quantity)) - existing_issued
                
                if quantity_issued > available_quantity:
                    validation_errors.append(
                        f"Cannot issue {quantity_issued}. Available quantity: {available_quantity}"
                    )
            except Exception as e:
                validation_errors.append(f"Error validating quantity availability: {str(e)}")
        
        # Validate metadata if present
        if 'metadata' in item_data:
            try:
                cls.validate_json_field(item_data['metadata'], "metadata")
            except ValidationError as e:
                field_errors.update(e.error_dict)
        
        # Raise combined errors if any exist
        if field_errors or validation_errors:
            error = ValidationError(f"Line item {line_number} validation failed")
            error.error_dict = field_errors
            error.error_list = validation_errors
            raise error
        
        return True


class TransferReceiptValidator(TransferDataValidator):
    """
    Validator for transfer receipt data
    """
    
    @classmethod
    def validate_transfer_receipt_creation(cls, goods_issue, destination_store, line_items_data, user):
        """
        Validate transfer receipt creation data
        """
        field_errors = {}
        validation_errors = []
        
        # Validate input parameters
        try:
            cls.validate_model_instance(goods_issue, type(goods_issue), "goods_issue")
        except ValidationError as e:
            field_errors.update(e.error_dict)
        
        try:
            cls.validate_model_instance(destination_store, type(destination_store), "destination_store")
        except ValidationError as e:
            field_errors.update(e.error_dict)
        
        try:
            cls.validate_model_instance(user, type(user), "user")
        except ValidationError as e:
            field_errors.update(e.error_dict)
        
        # Validate goods issue and store relationship
        if goods_issue and destination_store and destination_store != goods_issue.sales_order.destination_store:
            validation_errors.append(
                f"Destination store '{destination_store.store_name}' does not match "
                f"sales order destination store '{goods_issue.sales_order.destination_store.store_name}'"
            )
        
        # Validate goods issue has been posted to external systems
        if goods_issue and not goods_issue.posted_to_icg:
            validation_errors.append("Goods issue must be posted to ICG before creating transfer receipt")
        
        if goods_issue and not goods_issue.posted_to_sap:
            validation_errors.append("Goods issue must be posted to SAP ByD before creating transfer receipt")
        
        # Validate line items
        if not line_items_data:
            validation_errors.append("At least one line item is required")
        elif not isinstance(line_items_data, list):
            field_errors["line_items"] = ["Line items must be a list"]
        else:
            for i, item_data in enumerate(line_items_data):
                try:
                    cls.validate_transfer_receipt_line_item(item_data, goods_issue, i + 1)
                except ValidationError as e:
                    if hasattr(e, 'error_dict'):
                        for field, errors in e.error_dict.items():
                            field_key = f"line_items[{i}].{field}"
                            field_errors[field_key] = errors
                    else:
                        validation_errors.append(f"Line item {i + 1}: {str(e)}")
        
        # Raise combined errors if any exist
        if field_errors or validation_errors:
            error = ValidationError("Transfer receipt validation failed")
            error.error_dict = field_errors
            error.error_list = validation_errors
            raise error
        
        return True
    
    @classmethod
    def validate_transfer_receipt_line_item(cls, item_data, goods_issue, line_number):
        """
        Validate individual transfer receipt line item
        """
        field_errors = {}
        validation_errors = []
        
        if not isinstance(item_data, dict):
            raise ValidationError(f"Line item {line_number} must be a valid dictionary")
        
        # Validate required fields
        if 'goods_issue_line_item' not in item_data or item_data['goods_issue_line_item'] is None:
            field_errors["goods_issue_line_item"] = ["goods_issue_line_item is required"]
        
        if 'quantity_received' not in item_data or item_data['quantity_received'] is None:
            field_errors["quantity_received"] = ["quantity_received is required"]
        
        # If basic validation failed, return early
        if field_errors:
            error = ValidationError(f"Line item {line_number} validation failed")
            error.error_dict = field_errors
            raise error
        
        gi_line_item = item_data['goods_issue_line_item']
        quantity_received = item_data['quantity_received']
        
        # Validate line item belongs to goods issue
        if goods_issue and gi_line_item.goods_issue != goods_issue:
            validation_errors.append("Line item does not belong to the specified goods issue")
        
        # Validate quantity received
        try:
            quantity_received = cls.validate_positive_decimal(quantity_received, "quantity_received")
        except ValidationError as e:
            field_errors.update(e.error_dict if hasattr(e, 'error_dict') else {"quantity_received": [str(e)]})
        
        # Validate quantity doesn't exceed issued quantity
        if not field_errors and not validation_errors:
            try:
                existing_received = gi_line_item.transfer_receipt_items.aggregate(
                    total=Sum('quantity_received')
                )['total'] or Decimal('0')
                
                available_quantity = Decimal(str(gi_line_item.quantity_issued)) - existing_received
                
                if quantity_received > available_quantity:
                    validation_errors.append(
                        f"Cannot receive {quantity_received}. Available quantity: {available_quantity}"
                    )
            except Exception as e:
                validation_errors.append(f"Error validating quantity availability: {str(e)}")
        
        # Validate metadata if present
        if 'metadata' in item_data:
            try:
                cls.validate_json_field(item_data['metadata'], "metadata")
            except ValidationError as e:
                field_errors.update(e.error_dict)
        
        # Raise combined errors if any exist
        if field_errors or validation_errors:
            error = ValidationError(f"Line item {line_number} validation failed")
            error.error_dict = field_errors
            error.error_list = validation_errors
            raise error
        
        return True


class StoreAuthorizationValidator(TransferDataValidator):
    """
    Validator for store authorization data
    """
    
    @classmethod
    def validate_store_access(cls, user, byd_cost_center_code, required_roles=None):
        """
        Validate user has access to a specific store
        """
        field_errors = {}
        validation_errors = []
        
        # Validate user
        if not user:
            field_errors["user"] = ["User is required"]
        elif not user.is_authenticated:
            validation_errors.append("User must be authenticated")
        
        # Validate store_id
        if not byd_cost_center_code:
            field_errors["byd_cost_center_code"] = ["ByD Cost Center Code is required"]
        
        # Validate required_roles if provided
        if required_roles is not None:
            if not isinstance(required_roles, (list, tuple)):
                field_errors["required_roles"] = ["Required roles must be a list or tuple"]
            elif not all(isinstance(role, str) for role in required_roles):
                field_errors["required_roles"] = ["All required roles must be strings"]
        
        # If basic validation failed, raise error
        if field_errors or validation_errors:
            error = ValidationError("Store authorization validation failed")
            error.error_dict = field_errors
            error.error_list = validation_errors
            raise error
        
        # Check if user has authorization for the store
        try:
            store = Store.objects.get(byd_cost_center_code=byd_cost_center_code)
            authorization = StoreAuthorization.objects.filter(
                user=user,
                store=store
            ).first()
            
            if not authorization:
                raise ValidationError(f"User '{user.username}' is not authorized for store {store.store_name}")
            
            # Check role requirements if specified
            if required_roles and authorization.role not in required_roles:
                raise ValidationError(
                    f"User '{user.username}' does not have required role for store {store.store_name}. "
                    f"Required: {', '.join(required_roles)}, Current: {authorization.role}"
                )
            
            return authorization
            
        except Exception as e:
            if isinstance(e, ValidationError):
                raise e
            else:
                raise ValidationError(f"Error validating store authorization: {str(e)}")
    
    @classmethod
    def validate_store_authorization_data(cls, user, store, role):
        """
        Validate store authorization creation data
        """
        field_errors = {}
        validation_errors = []
        
        # Validate user
        try:
            cls.validate_model_instance(user, type(user), "user")
        except ValidationError as e:
            field_errors.update(e.error_dict)
        
        # Validate store
        try:
            cls.validate_model_instance(store, type(store), "store")
        except ValidationError as e:
            field_errors.update(e.error_dict)
        
        # Validate role
        if role:
            try:
                valid_roles = [choice[0] for choice in StoreAuthorization.STORE_ROLE_CHOICES]
                FieldValidator.validate_choice_field(role, "role", StoreAuthorization.STORE_ROLE_CHOICES)
            except ValidationError as e:
                field_errors.update(e.error_dict)
        else:
            field_errors["role"] = ["Role is required"]
        
        # Check for duplicate authorization
        if user and store and not field_errors:
            existing = StoreAuthorization.objects.filter(user=user, store=store).first()
            if existing:
                validation_errors.append(f"User '{user.username}' already has authorization for store '{store.store_name}'")
        
        # Raise combined errors if any exist
        if field_errors or validation_errors:
            error = ValidationError("Store authorization data validation failed")
            error.error_dict = field_errors
            error.error_list = validation_errors
            raise error
        
        return True


class InventoryValidator(TransferDataValidator):
    """
    Validator for inventory-related operations
    """
    
    @classmethod
    def validate_inventory_availability(cls, store_id, product_items):
        """
        Validate inventory availability for goods issue
        This is a placeholder for ICG integration
        """
        errors = []
        
        if not store_id:
            errors.append("Store ID is required for inventory validation")
        
        if not product_items:
            errors.append("Product items are required for inventory validation")
        
        # Placeholder validation - in real implementation, this would check ICG
        for i, item in enumerate(product_items):
            if not item.get('product_id'):
                errors.append(f"Item {i + 1}: Product ID is required")
            
            if not item.get('quantity'):
                errors.append(f"Item {i + 1}: Quantity is required")
            else:
                try:
                    cls.validate_positive_decimal(item['quantity'], f"Item {i + 1} quantity")
                except ValidationError as e:
                    errors.append(str(e))
        
        if errors:
            raise ValidationError(errors)
        
        # Placeholder: assume inventory is available
        # Real implementation would call ICG API to check actual inventory levels
        logger.info(f"Inventory validation placeholder for store {store_id}")
        
        return True


class BusinessRuleValidator(TransferDataValidator):
    """
    Validator for business rules and constraints
    """
    
    @classmethod
    def validate_transfer_business_rules(cls, sales_order, goods_issue_data=None, receipt_data=None):
        """
        Validate business rules for transfer operations
        """
        errors = []
        
        # Validate sales order status - use stored status code for business rules
        if sales_order.delivery_status_code == '3':  # Completely Delivered
            errors.append("Cannot create additional transfers for a completely delivered sales order")
        
        # Validate goods issue business rules
        if goods_issue_data:
            # Check if there are already goods issues for this sales order
            existing_issues = sales_order.goods_issues.count()
            if existing_issues >= 10:  # Business rule: max 10 goods issues per sales order
                errors.append("Maximum number of goods issues (10) reached for this sales order")
        
        # Validate receipt business rules
        if receipt_data:
            goods_issue = receipt_data.get('goods_issue')
            if goods_issue:
                # Check if goods issue is already fully received
                total_issued = sum(float(item.quantity_issued) for item in goods_issue.line_items.all())
                total_received = sum(
                    float(receipt_item.quantity_received)
                    for gi_item in goods_issue.line_items.all()
                    for receipt_item in gi_item.transfer_receipt_items.all()
                )
                
                if total_received >= total_issued:
                    errors.append("Goods issue is already fully received")
        
        if errors:
            raise ValidationError(errors)
        
        return True
    
    @classmethod
    def validate_sales_order_status_for_operation(cls, sales_order, operation_type):
        """
        Validate sales order status allows the requested operation
        """
        errors = []
        
        # Use stored delivery status code for validation
        delivery_status_code = sales_order.delivery_status_code
        
        if operation_type == 'goods_issue':
            if delivery_status_code == '3':  # Completely Delivered
                errors.append("Cannot create goods issue for a completely delivered sales order")
        elif operation_type == 'transfer_receipt':
            # For transfer receipt, check if there are any goods issues
            if not sales_order.goods_issues.exists():
                errors.append("Cannot create transfer receipt for a sales order with no goods issued")
        
        if errors:
            raise ValidationError(errors)
        
        return True
    
    @classmethod
    def validate_quantity_constraints(cls, line_items_data, operation_type):
        """
        Validate quantity constraints for transfer operations
        """
        errors = []
        
        for i, item_data in enumerate(line_items_data):
            line_number = i + 1
            
            if operation_type == 'goods_issue':
                so_line_item = item_data.get('sales_order_line_item')
                quantity_issued = item_data.get('quantity_issued', 0)
                
                if so_line_item:
                    # Check if quantity exceeds remaining available quantity
                    existing_issued = so_line_item.goods_issue_items.aggregate(
                        total=Sum('quantity_issued')
                    )['total'] or Decimal('0')
                    
                    available_quantity = Decimal(str(so_line_item.quantity)) - existing_issued
                    
                    if Decimal(str(quantity_issued)) > available_quantity:
                        errors.append(
                            f"Line item {line_number}: Cannot issue {quantity_issued}. "
                            f"Available quantity: {available_quantity}"
                        )
            
            elif operation_type == 'transfer_receipt':
                gi_line_item = item_data.get('goods_issue_line_item')
                quantity_received = item_data.get('quantity_received', 0)
                
                if gi_line_item:
                    # Check if quantity exceeds remaining receivable quantity
                    existing_received = gi_line_item.transfer_receipt_items.aggregate(
                        total=Sum('quantity_received')
                    )['total'] or Decimal('0')
                    
                    available_quantity = Decimal(str(gi_line_item.quantity_issued)) - existing_received
                    
                    if Decimal(str(quantity_received)) > available_quantity:
                        errors.append(
                            f"Line item {line_number}: Cannot receive {quantity_received}. "
                            f"Available quantity: {available_quantity}"
                        )
        
        if errors:
            raise ValidationError(errors)
        
        return True
    
    @classmethod
    def validate_store_relationship_constraints(cls, sales_order, source_store=None, destination_store=None):
        """
        Validate store relationships match sales order requirements
        """
        errors = []
        
        if source_store and source_store != sales_order.source_store:
            errors.append(
                f"Source store {source_store.store_name} does not match "
                f"sales order source store {sales_order.source_store.store_name}"
            )
        
        if destination_store and destination_store != sales_order.destination_store:
            errors.append(
                f"Destination store {destination_store.store_name} does not match "
                f"sales order destination store {sales_order.destination_store.store_name}"
            )
        
        if errors:
            raise ValidationError(errors)
        
        return True
    
    @classmethod
    def validate_line_item_relationships(cls, line_items_data, parent_object, operation_type):
        """
        Validate line item relationships are correct for the operation
        """
        errors = []
        
        for i, item_data in enumerate(line_items_data):
            line_number = i + 1
            
            if operation_type == 'goods_issue':
                so_line_item = item_data.get('sales_order_line_item')
                if so_line_item and so_line_item.sales_order != parent_object:
                    errors.append(
                        f"Line item {line_number}: Sales order line item does not belong "
                        f"to the specified sales order"
                    )
            
            elif operation_type == 'transfer_receipt':
                gi_line_item = item_data.get('goods_issue_line_item')
                if gi_line_item and gi_line_item.goods_issue != parent_object:
                    errors.append(
                        f"Line item {line_number}: Goods issue line item does not belong "
                        f"to the specified goods issue"
                    )
        
        if errors:
            raise ValidationError(errors)
        
        return True
    
    @classmethod
    def validate_transfer_completion_rules(cls, goods_issue):
        """
        Validate rules for transfer completion
        """
        errors = []
        
        # Check if goods issue has been posted to external systems
        if not goods_issue.posted_to_icg:
            errors.append("Goods issue must be posted to ICG before creating transfer receipt")
        
        if not goods_issue.posted_to_sap:
            errors.append("Goods issue must be posted to SAP ByD before creating transfer receipt")
        
        # Check if goods issue has line items
        if not goods_issue.line_items.exists():
            errors.append("Goods issue must have line items before creating transfer receipt")
        
        if errors:
            raise ValidationError(errors)
        
        return True