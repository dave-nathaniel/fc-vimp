"""
Business logic services for warehouse-to-store transfers
"""
import logging
from django.db.models import QuerySet
from django.core.exceptions import ValidationError
from core_service.models import CustomUser
from egrn_service.models import Store
from .models import InboundDelivery, StoreAuthorization

logger = logging.getLogger(__name__)


class AuthorizationService:
    """
    Service for managing store authorization and access control
    """

    @staticmethod
    def get_user_authorized_stores(user: CustomUser) -> QuerySet[Store]:
        """
        Get all stores that a user is authorized to access.
        - SCD_Team and Finance members can access ALL stores
        - Other users access stores via StoreAuthorization
        """
        # SCD_Team and Finance have global access to all stores
        if AuthorizationService.has_global_delivery_access(user):
            return Store.objects.all()

        return Store.objects.filter(authorized_users__user=user)

    @staticmethod
    def validate_store_access(user: CustomUser, byd_cost_center_code: str) -> bool:
        """
        Validate if a user has access to a specific store.
        - SCD_Team and Finance members have access to ALL stores
        - Other users check via StoreAuthorization
        """
        # SCD_Team and Finance have global access
        if AuthorizationService.has_global_delivery_access(user):
            return True

        store = Store.objects.get(byd_cost_center_code=byd_cost_center_code)
        return StoreAuthorization.objects.filter(
            user=user,
            store=store
        ).exists()

    @staticmethod
    def validate_store_access_with_role(user: CustomUser, byd_cost_center_code: str, required_roles: list = None) -> bool:
        """
        Validate if a user has access to a specific store with required role
        """
        store = Store.objects.get(byd_cost_center_code=byd_cost_center_code)
        query = StoreAuthorization.objects.filter(user=user, store=store)

        if required_roles:
            query = query.filter(role__in=required_roles)

        return query.exists()

    @staticmethod
    def get_user_store_role(user: CustomUser, byd_cost_center_code: str) -> str:
        """
        Get user's role for a specific store
        """
        try:
            store = Store.objects.get(byd_cost_center_code=byd_cost_center_code)
            auth = StoreAuthorization.objects.get(user=user, store=store)
            return auth.role
        except StoreAuthorization.DoesNotExist:
            return None
    
    @staticmethod
    def validate_transfer_authorization(user: CustomUser, sales_order, operation_type: str) -> bool:
        """
        Validate user authorization for transfer operations
        """
        from .validators import StoreAuthorizationValidator
        
        if operation_type == 'goods_issue':
            # User must have access to source store
            StoreAuthorizationValidator.validate_store_access(
                user, sales_order.source_store.id, 
                required_roles=['manager', 'assistant', 'clerk']
            )
        elif operation_type == 'transfer_receipt':
            # User must have access to destination store
            StoreAuthorizationValidator.validate_store_access(
                user, sales_order.destination_store.id,
                required_roles=['manager', 'assistant', 'clerk']
            )
        elif operation_type == 'view':
            # User must have access to either source or destination store
            source_access = AuthorizationService.validate_store_access(user, sales_order.source_store.id)
            dest_access = AuthorizationService.validate_store_access(user, sales_order.destination_store.id)
            
            if not (source_access or dest_access):
                raise ValidationError(
                    f"User {user.username} is not authorized to view this transfer"
                )
        
        return True
    
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

    @staticmethod
    def is_scd_team_member(user: CustomUser) -> bool:
        """
        Check if user is a member of the SCD_Team group (Azure AD role).
        SCD_Team members have access to all source locations for approval.
        """
        return user.groups.filter(name='SCD_Team').exists()

    @staticmethod
    def is_restaurant_manager(user: CustomUser) -> bool:
        """
        Check if user is a member of the Restaurant_Manager group (Azure AD role).
        Restaurant managers can update rejected receipts.
        """
        return user.groups.filter(name='Restaurant_Manager').exists()

    @staticmethod
    def is_finance_member(user: CustomUser) -> bool:
        """
        Check if user is a member of the Finance group (Azure AD role).
        Finance members have read access to all deliveries.
        """
        return user.groups.filter(name='Finance').exists()

    @staticmethod
    def has_global_delivery_access(user: CustomUser) -> bool:
        """
        Check if user has global access to view all deliveries.
        SCD_Team and Finance members can view all stores' deliveries.
        """
        return (
            AuthorizationService.is_scd_team_member(user) or
            AuthorizationService.is_finance_member(user)
        )

    @staticmethod
    def get_user_authorized_source_locations(user: CustomUser) -> list:
        """
        Get source locations (warehouses/stores) user can approve receipts for.
        - SCD_Team members can approve for ALL source locations
        - Other users use StoreAuthorization with manager/assistant roles
        """
        # SCD_Team members can approve for all locations
        if AuthorizationService.is_scd_team_member(user):
            return None  # None indicates all locations

        authorized_stores = Store.objects.filter(
            authorized_users__user=user,
            authorized_users__role__in=['manager', 'assistant']
        ).values_list('byd_cost_center_code', flat=True)

        return list(authorized_stores)

    @staticmethod
    def validate_source_location_access(user: CustomUser, source_location_id: str) -> bool:
        """
        Validate if user can approve receipts from a specific source location.
        - SCD_Team members can approve for ALL locations
        - Other users use StoreAuthorization model
        """
        # SCD_Team members have access to all locations
        if AuthorizationService.is_scd_team_member(user):
            return True

        authorized_locations = AuthorizationService.get_user_authorized_source_locations(user)
        return source_location_id in (authorized_locations or [])


class DeliveryService:
    """
    Service for managing inbound delivery operations
    """

    def __init__(self):
        from byd_service.rest import RESTServices
        self.byd_rest = RESTServices()

    def search_deliveries_by_id(self, delivery_id: str, user_byd_cost_center_codes: list) -> dict:
        """
        Search for deliveries by ID across local database and SAP ByD
        """
        results = {
            'local': [],
            'sap_byd': []
        }

        # Search local database first
        local_deliveries = InboundDelivery.objects.filter(
            delivery_id__icontains=delivery_id,
            destination_store__byd_cost_center_code__in=user_byd_cost_center_codes
        )

        for delivery in local_deliveries:
            results['local'].append(delivery)

        # If no local results, search SAP ByD
        if not results['local']:
            for byd_cost_center_code in user_byd_cost_center_codes:
                try:
                    byd_deliveries = self.byd_rest.search_deliveries_by_store(byd_cost_center_code)
                    matching_deliveries = [
                        d for d in byd_deliveries
                        if delivery_id.lower() in d.get('ID', '').lower()
                    ]
                    results['sap_byd'].extend(matching_deliveries)
                except Exception as e:
                    logger.warning(f"Error searching SAP ByD for store {byd_cost_center_code}: {e}")
                    continue

        return results

    def fetch_and_create_delivery(self, delivery_id: str):
        """
        Fetch delivery from SAP ByD and create local record
        """
        try:
            delivery_data = self.byd_rest.get_delivery_by_id(delivery_id)
            if not delivery_data:
                raise ValidationError(f"Delivery {delivery_id} not found in SAP ByD")

            return InboundDelivery.create_from_byd_data(delivery_data)
        except Exception as e:
            logger.error(f"Error fetching delivery {delivery_id}: {e}")
            raise
