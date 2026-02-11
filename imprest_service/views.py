from rest_framework.decorators import api_view, authentication_classes
from rest_framework import status
from django.db.models import Q
from overrides.rest_framework import APIResponse, CustomPagination
from overrides.authenticate import CombinedAuthentication
from .models import ImprestItem
from .serializers import ImprestItemSerializer, ImprestItemBriefSerializer
import logging

logger = logging.getLogger(__name__)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_imprest_items(request):
    """
    GET /imprest/v1/items/

    Fetch G/L Accounts (Imprest Items) from local DB or sync from SAP ByD.

    Query Parameters:
        - refresh (bool): Force refresh from SAP ByD (true/false). Default: false
        - account_type (str): Filter by account type (COSEXP, CASH, OTHER)
        - is_active (bool): Filter by active status (true/false)
        - search (str): Search in GL account number or description
        - page (int): Page number for pagination
        - size (int): Page size (max 1000)

    Returns:
        200: List of imprest items with pagination
        500: Error syncing from SAP ByD
    """
    try:
        # Get query parameters
        refresh = request.query_params.get('refresh', '').lower() == 'true'
        account_type = request.query_params.get('account_type', '').upper()
        is_active = request.query_params.get('is_active', '').lower()
        search = request.query_params.get('search', '').strip()

        # Check if we need to sync from SAP ByD
        queryset = ImprestItem.objects.all()

        # If DB is empty or refresh is requested, sync from SAP ByD
        if not queryset.exists() or refresh:
            logger.info(f"Syncing imprest items from SAP ByD (refresh={refresh})")

            # Sync with optional account type filter
            sync_account_type = account_type if account_type in ['COSEXP', 'CASH'] else None
            sync_result = ImprestItem.sync_from_byd(
                account_type=sync_account_type,
                force_refresh=refresh
            )

            logger.info(f"Sync result: {sync_result}")

            # Refresh queryset after sync
            queryset = ImprestItem.objects.all()

        # Apply filters
        if account_type:
            queryset = queryset.filter(account_type=account_type)

        if is_active == 'true':
            queryset = queryset.filter(is_active=True)
        elif is_active == 'false':
            queryset = queryset.filter(is_active=False)

        # Apply search filter
        if search:
            queryset = queryset.filter(
                Q(gl_account__icontains=search) |
                Q(description__icontains=search)
            )

        # Order by GL account
        queryset = queryset.order_by('gl_account')

        # Paginate results
        paginator = CustomPagination()
        paginated_queryset = paginator.paginate_queryset(queryset, request)

        # Use brief serializer for list view (performance)
        serializer = ImprestItemBriefSerializer(paginated_queryset, many=True)

        return APIResponse(
            status=status.HTTP_200_OK,
            message='Imprest items retrieved successfully',
            data=paginator.get_paginated_response(serializer.data).data
        )

    except Exception as e:
        logger.error(f"Error fetching imprest items: {str(e)}", exc_info=True)
        return APIResponse(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f'Error fetching imprest items: {str(e)}',
            data=None
        )


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_imprest_item(request, gl_account):
    """
    GET /imprest/v1/items/<gl_account>/

    Fetch a specific G/L Account by account number.

    Path Parameters:
        - gl_account (str): G/L Account number

    Query Parameters:
        - refresh (bool): Force refresh from SAP ByD (true/false)

    Returns:
        200: Imprest item details
        404: Item not found
        500: Error
    """
    try:
        refresh = request.query_params.get('refresh', '').lower() == 'true'

        # If refresh is requested, sync from SAP ByD
        if refresh:
            logger.info(f"Refreshing imprest item {gl_account} from SAP ByD")
            ImprestItem.sync_from_byd(force_refresh=True)

        # Try to get the item
        try:
            item = ImprestItem.objects.get(gl_account=gl_account)
        except ImprestItem.DoesNotExist:
            # If not found and refresh not already done, try syncing
            if not refresh:
                logger.info(f"Item {gl_account} not found, syncing from SAP ByD")
                ImprestItem.sync_from_byd(force_refresh=False)

                # Try again
                try:
                    item = ImprestItem.objects.get(gl_account=gl_account)
                except ImprestItem.DoesNotExist:
                    return APIResponse(
                        status=status.HTTP_404_NOT_FOUND,
                        message=f'G/L Account {gl_account} not found',
                        data=None
                    )
            else:
                return APIResponse(
                    status=status.HTTP_404_NOT_FOUND,
                    message=f'G/L Account {gl_account} not found',
                    data=None
                )

        serializer = ImprestItemSerializer(item)
        return APIResponse(
            status=status.HTTP_200_OK,
            message='Imprest item retrieved successfully',
            data=serializer.data
        )

    except Exception as e:
        logger.error(f"Error fetching imprest item {gl_account}: {str(e)}", exc_info=True)
        return APIResponse(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f'Error fetching imprest item: {str(e)}',
            data=None
        )


@api_view(['POST'])
@authentication_classes([CombinedAuthentication])
def sync_imprest_items(request):
    """
    POST /imprest/v1/sync/

    Manually trigger sync of G/L Accounts from SAP ByD.

    Request Body (optional):
        {
            "account_type": "COSEXP" | "CASH",  // Optional filter
            "force_refresh": true | false        // Delete existing and re-sync
        }

    Returns:
        200: Sync completed successfully with statistics
        500: Error syncing
    """
    try:
        # Get request parameters
        account_type = request.data.get('account_type', '').upper()
        force_refresh = request.data.get('force_refresh', False)

        # Validate account type if provided
        if account_type and account_type not in ['COSEXP', 'CASH']:
            return APIResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message='Invalid account_type. Must be COSEXP or CASH',
                data=None
            )

        # Sync from SAP ByD
        logger.info(f"Manual sync triggered (account_type={account_type}, force_refresh={force_refresh})")
        sync_result = ImprestItem.sync_from_byd(
            account_type=account_type if account_type else None,
            force_refresh=force_refresh
        )

        return APIResponse(
            status=status.HTTP_200_OK,
            message=sync_result['message'],
            data=sync_result
        )

    except Exception as e:
        logger.error(f"Error syncing imprest items: {str(e)}", exc_info=True)
        return APIResponse(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f'Error syncing imprest items: {str(e)}',
            data=None
        )


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_expense_accounts(request):
    """
    GET /imprest/v1/expense-accounts/

    Fetch expense accounts (COSEXP) for imprest management.
    Automatically syncs from SAP ByD if DB is empty.

    Query Parameters:
        - refresh (bool): Force refresh from SAP ByD
        - search (str): Search in GL account or description
        - page, size: Pagination

    Returns:
        200: List of expense accounts
    """
    try:
        refresh = request.query_params.get('refresh', '').lower() == 'true'
        search = request.query_params.get('search', '').strip()

        # Check if expense accounts exist in DB
        queryset = ImprestItem.get_expense_accounts()

        if not queryset.exists() or refresh:
            logger.info("Syncing expense accounts from SAP ByD")
            ImprestItem.sync_from_byd(account_type='COSEXP', force_refresh=refresh)
            queryset = ImprestItem.get_expense_accounts()

        # Apply search
        if search:
            queryset = queryset.filter(
                Q(gl_account__icontains=search) |
                Q(description__icontains=search)
            )

        queryset = queryset.order_by('gl_account')

        # Paginate
        paginator = CustomPagination()
        paginated = paginator.paginate_queryset(queryset, request)
        serializer = ImprestItemBriefSerializer(paginated, many=True)

        return APIResponse(
            status=status.HTTP_200_OK,
            message='Expense accounts retrieved successfully',
            data=paginator.get_paginated_response(serializer.data).data
        )

    except Exception as e:
        logger.error(f"Error fetching expense accounts: {str(e)}", exc_info=True)
        return APIResponse(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f'Error fetching expense accounts: {str(e)}',
            data=None
        )


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_bank_accounts(request):
    """
    GET /imprest/v1/bank-accounts/

    Fetch bank/cash accounts (CASH) for payment processing.
    Automatically syncs from SAP ByD if DB is empty.

    Query Parameters:
        - refresh (bool): Force refresh from SAP ByD
        - search (str): Search in GL account or description
        - page, size: Pagination

    Returns:
        200: List of bank accounts
    """
    try:
        refresh = request.query_params.get('refresh', '').lower() == 'true'
        search = request.query_params.get('search', '').strip()

        # Check if bank accounts exist in DB
        queryset = ImprestItem.get_bank_accounts()

        if not queryset.exists() or refresh:
            logger.info("Syncing bank accounts from SAP ByD")
            ImprestItem.sync_from_byd(account_type='CASH', force_refresh=refresh)
            queryset = ImprestItem.get_bank_accounts()

        # Apply search
        if search:
            queryset = queryset.filter(
                Q(gl_account__icontains=search) |
                Q(description__icontains=search)
            )

        queryset = queryset.order_by('gl_account')

        # Paginate
        paginator = CustomPagination()
        paginated = paginator.paginate_queryset(queryset, request)
        serializer = ImprestItemBriefSerializer(paginated, many=True)

        return APIResponse(
            status=status.HTTP_200_OK,
            message='Bank accounts retrieved successfully',
            data=paginator.get_paginated_response(serializer.data).data
        )

    except Exception as e:
        logger.error(f"Error fetching bank accounts: {str(e)}", exc_info=True)
        return APIResponse(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f'Error fetching bank accounts: {str(e)}',
            data=None
        )
