"""
Custom validation classes for transfer service data
"""
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation
import logging
from egrn_service.models import Store
from .models import StoreAuthorization

logger = logging.getLogger(__name__)


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


class StoreAuthorizationValidator:
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

        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Error validating store authorization: {str(e)}")

    @classmethod
    def validate_store_authorization_data(cls, user, store, role):
        """
        Validate store authorization creation data
        """
        field_errors = {}
        validation_errors = []

        if not user:
            field_errors["user"] = ["User is required"]

        if not store:
            field_errors["store"] = ["Store is required"]

        # Validate role
        if role:
            FieldValidator.validate_choice_field(role, "role", StoreAuthorization.STORE_ROLE_CHOICES)
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
