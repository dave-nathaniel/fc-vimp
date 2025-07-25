"""
Custom validation classes for transfer service data
"""
from django.core.exceptions import ValidationError
from django.db.models import Sum
from decimal import Decimal, InvalidOperation
from rest_framework import serializers
import logging

logger = logging.getLogger(__name__)


class TransferDataValidator:
    """
    Base validator class for transfer-related data validation
    """
    
    @staticmethod
    def validate_positive_decimal(value, field_name="value"):
        """
        Validate that a decimal value is positive
        """
        if value is None:
            raise ValidationError(f"{field_name} cannot be null")
        
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValidationError(f"{field_name} must be a valid decimal number")
        
        if decimal_value <= 0:
            raise ValidationError(f"{field_name} must be greater than 0")
        
        return decimal_value
    
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
        if value is None or (isinstance(value, str) and value.strip() == ""):
            raise ValidationError(f"{field_name} is required")
        
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
        errors = []
        
        # Required fields validation
        required_fields = ["ObjectID", "ID", "TotalNetAmount"]
        for field in required_fields:
            if field not in so_data or so_data[field] is None:
                errors.append(f"Required field '{field}' is missing or null")
        
        # Validate sales order ID is numeric
        if "ID" in so_data:
            try:
                int(so_data["ID"])
            except (ValueError, TypeError):
                errors.append("Sales order ID must be a valid integer")
        
        # Validate total net amount
        if "TotalNetAmount" in so_data:
            try:
                cls.validate_positive_decimal(so_data["TotalNetAmount"], "TotalNetAmount")
            except ValidationError as e:
                errors.append(str(e))
        
        # Validate party information
        seller_party = so_data.get("SellerParty", {})
        buyer_party = so_data.get("BuyerParty", {})
        
        if not seller_party.get("PartyID"):
            errors.append("SellerParty PartyID is required")
        
        if not buyer_party.get("PartyID"):
            errors.append("BuyerParty PartyID is required")
        
        # Validate line items exist
        items = so_data.get("Item", [])
        if not items:
            errors.append("Sales order must contain at least one line item")
        
        # Validate each line item
        for i, item in enumerate(items):
            item_errors = cls.validate_line_item_data(item, i + 1)
            errors.extend(item_errors)
        
        if errors:
            raise ValidationError(errors)
        
        return True
    
    @classmethod
    def validate_line_item_data(cls, item_data, line_number):
        """
        Validate sales order line item data
        """
        errors = []
        
        # Required fields for line items
        required_fields = ["ObjectID", "ProductID", "Description", "Quantity", "ListUnitPriceAmount"]
        for field in required_fields:
            if field not in item_data or item_data[field] is None:
                errors.append(f"Line item {line_number}: Required field '{field}' is missing or null")
        
        # Validate quantity
        if "Quantity" in item_data:
            try:
                cls.validate_positive_decimal(item_data["Quantity"], f"Line item {line_number} Quantity")
            except ValidationError as e:
                errors.append(str(e))
        
        # Validate unit price
        if "ListUnitPriceAmount" in item_data:
            try:
                cls.validate_positive_decimal(item_data["ListUnitPriceAmount"], f"Line item {line_number} ListUnitPriceAmount")
            except ValidationError as e:
                errors.append(str(e))
        
        return errors


class GoodsIssueValidator(TransferDataValidator):
    """
    Validator for goods issue data
    """
    
    @classmethod
    def validate_goods_issue_creation(cls, sales_order, source_store, line_items_data, user):
        """
        Validate goods issue creation data
        """
        errors = []
        
        # Validate sales order and store relationship
        if source_store != sales_order.source_store:
            errors.append("Source store must match the sales order source store")
        
        # Validate line items
        if not line_items_data:
            errors.append("At least one line item is required")
        else:
            for i, item_data in enumerate(line_items_data):
                item_errors = cls.validate_goods_issue_line_item(item_data, sales_order, i + 1)
                errors.extend(item_errors)
        
        if errors:
            raise ValidationError(errors)
        
        return True
    
    @classmethod
    def validate_goods_issue_line_item(cls, item_data, sales_order, line_number):
        """
        Validate individual goods issue line item
        """
        errors = []
        
        # Validate required fields
        if 'sales_order_line_item' not in item_data:
            errors.append(f"Line item {line_number}: sales_order_line_item is required")
            return errors
        
        if 'quantity_issued' not in item_data:
            errors.append(f"Line item {line_number}: quantity_issued is required")
            return errors
        
        so_line_item = item_data['sales_order_line_item']
        quantity_issued = item_data['quantity_issued']
        
        # Validate line item belongs to sales order
        if so_line_item.sales_order != sales_order:
            errors.append(f"Line item {line_number}: Line item does not belong to the specified sales order")
        
        # Validate quantity issued
        try:
            quantity_issued = cls.validate_positive_decimal(quantity_issued, f"Line item {line_number} quantity_issued")
        except ValidationError as e:
            errors.append(str(e))
            return errors
        
        # Validate quantity doesn't exceed available quantity
        existing_issued = so_line_item.goods_issue_items.aggregate(
            total=Sum('quantity_issued')
        )['total'] or Decimal('0')
        
        available_quantity = Decimal(str(so_line_item.quantity)) - existing_issued
        
        if quantity_issued > available_quantity:
            errors.append(
                f"Line item {line_number}: Cannot issue {quantity_issued}. "
                f"Available quantity: {available_quantity}"
            )
        
        return errors


class TransferReceiptValidator(TransferDataValidator):
    """
    Validator for transfer receipt data
    """
    
    @classmethod
    def validate_transfer_receipt_creation(cls, goods_issue, destination_store, line_items_data, user):
        """
        Validate transfer receipt creation data
        """
        errors = []
        
        # Validate goods issue and store relationship
        if destination_store != goods_issue.sales_order.destination_store:
            errors.append("Destination store must match the sales order destination store")
        
        # Validate line items
        if not line_items_data:
            errors.append("At least one line item is required")
        else:
            for i, item_data in enumerate(line_items_data):
                item_errors = cls.validate_transfer_receipt_line_item(item_data, goods_issue, i + 1)
                errors.extend(item_errors)
        
        if errors:
            raise ValidationError(errors)
        
        return True
    
    @classmethod
    def validate_transfer_receipt_line_item(cls, item_data, goods_issue, line_number):
        """
        Validate individual transfer receipt line item
        """
        errors = []
        
        # Validate required fields
        if 'goods_issue_line_item' not in item_data:
            errors.append(f"Line item {line_number}: goods_issue_line_item is required")
            return errors
        
        if 'quantity_received' not in item_data:
            errors.append(f"Line item {line_number}: quantity_received is required")
            return errors
        
        gi_line_item = item_data['goods_issue_line_item']
        quantity_received = item_data['quantity_received']
        
        # Validate line item belongs to goods issue
        if gi_line_item.goods_issue != goods_issue:
            errors.append(f"Line item {line_number}: Line item does not belong to the specified goods issue")
        
        # Validate quantity received
        try:
            quantity_received = cls.validate_positive_decimal(quantity_received, f"Line item {line_number} quantity_received")
        except ValidationError as e:
            errors.append(str(e))
            return errors
        
        # Validate quantity doesn't exceed issued quantity
        existing_received = gi_line_item.transfer_receipt_items.aggregate(
            total=Sum('quantity_received')
        )['total'] or Decimal('0')
        
        available_quantity = Decimal(str(gi_line_item.quantity_issued)) - existing_received
        
        if quantity_received > available_quantity:
            errors.append(
                f"Line item {line_number}: Cannot receive {quantity_received}. "
                f"Available quantity: {available_quantity}"
            )
        
        return errors


class StoreAuthorizationValidator(TransferDataValidator):
    """
    Validator for store authorization data
    """
    
    @classmethod
    def validate_store_access(cls, user, store_id, required_roles=None):
        """
        Validate user has access to a specific store
        """
        from .models import StoreAuthorization
        
        if not user or not user.is_authenticated:
            raise ValidationError("User must be authenticated")
        
        if not store_id:
            raise ValidationError("Store ID is required")
        
        # Check if user has authorization for the store
        authorization = StoreAuthorization.objects.filter(
            user=user,
            store_id=store_id
        ).first()
        
        if not authorization:
            raise ValidationError(f"User {user.username} is not authorized for store {store_id}")
        
        # Check role requirements if specified
        if required_roles and authorization.role not in required_roles:
            raise ValidationError(
                f"User {user.username} does not have required role for store {store_id}. "
                f"Required: {required_roles}, Current: {authorization.role}"
            )
        
        return authorization


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