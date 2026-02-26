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
        Get all stores that a user is authorized to access
        """
        return Store.objects.filter(authorized_users__user=user)

    @staticmethod
    def validate_store_access(user: CustomUser, byd_cost_center_code: str) -> bool:
        """
        Validate if a user has access to a specific store
        """
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
