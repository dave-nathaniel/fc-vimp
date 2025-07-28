import logging
from datetime import datetime
from django.forms import model_to_dict
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from overrides.authenticate import CombinedAuthentication
from overrides.rest_framework import CustomPagination, APIResponse
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q, Sum, F

from .models import (
    SalesOrder, SalesOrderLineItem, GoodsIssueNote, GoodsIssueLineItem,
    TransferReceiptNote, TransferReceiptLineItem, StoreAuthorization
)
from .serializers import (
    SalesOrderSerializer, GoodsIssueNoteSerializer, TransferReceiptNoteSerializer,
    CreateGoodsIssueSerializer, CreateTransferReceiptSerializer, StoreAuthorizationSerializer
)
from .services import (
    SalesOrderService, GoodsIssueService, TransferReceiptService, AuthorizationService
)
from egrn_service.models import Store

# Get the user model
User = get_user_model()
# Pagination
paginator = CustomPagination()

# Initialize services
sales_order_service = SalesOrderService()
goods_issue_service = GoodsIssueService()
transfer_receipt_service = TransferReceiptService()
auth_service = AuthorizationService()


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_sales_orders(request):
    """
    Get sales orders for authorized stores
    """
    try:
        user_stores = auth_service.get_user_authorized_stores(request.user)
        
        # Get sales orders for user's stores
        sales_orders = SalesOrder.objects.filter(
            Q(source_store__in=user_stores) | Q(destination_store__in=user_stores)
        ).order_by('-order_date')
        
        if sales_orders.exists():
            # Paginate the results
            paginated = paginator.paginate_queryset(sales_orders, request)
            serializer = SalesOrderSerializer(paginated, many=True, context={'request': request})
            paginated_data = paginator.get_paginated_response(serializer.data).data
            return APIResponse("Sales Orders Retrieved", status.HTTP_200_OK, data=paginated_data)
        
        return APIResponse("No sales orders found for your stores.", status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        logging.error(f"Error retrieving sales orders: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_sales_order(request, sales_order_id):
    """
    Get a specific sales order by ID
    """
    try:
        user_stores = auth_service.get_user_authorized_stores(request.user)
        
        try:
            # Try to get from database first
            sales_order = SalesOrder.objects.get(sales_order_id=sales_order_id)
        except ObjectDoesNotExist:
            # If not in database, fetch from SAP ByD
            so_data = sales_order_service.fetch_sales_order_by_id(str(sales_order_id))
            if so_data:
                # Create sales order from SAP ByD data
                so = SalesOrder()
                sales_order = so.create_sales_order(so_data)
            else:
                return APIResponse(f"Sales order {sales_order_id} not found.", status.HTTP_404_NOT_FOUND)
        
        # Check if user has access to this sales order
        if not (sales_order.source_store in user_stores or sales_order.destination_store in user_stores):
            return APIResponse("You don't have access to this sales order.", status.HTTP_403_FORBIDDEN)
        
        serializer = SalesOrderSerializer(sales_order, context={'request': request})
        return APIResponse("Sales Order Retrieved", status.HTTP_200_OK, data=serializer.data)
    
    except Exception as e:
        logging.error(f"Error retrieving sales order {sales_order_id}: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([CombinedAuthentication])
def create_goods_issue(request):
    """
    Create a goods issue note
    """
    try:
        serializer = CreateGoodsIssueSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse("Invalid input data.", status.HTTP_400_BAD_REQUEST, 
                             data=serializer.errors)
        
        validated_data = serializer.validated_data
        sales_order_id = validated_data['sales_order_id']
        
        # Get the sales order
        sales_order = SalesOrder.objects.get(sales_order_id=sales_order_id)
        
        # Check if user has access to source store
        if not auth_service.validate_store_access(request.user, sales_order.source_store.id):
            return APIResponse("You don't have access to the source store.", status.HTTP_403_FORBIDDEN)
        
        # Validate inventory availability
        items_to_validate = []
        for item in validated_data['issued_goods']:
            items_to_validate.append({
                'product_id': item.get('productID'),
                'quantity': float(item.get('quantityIssued', 0))
            })
        
        if not goods_issue_service.validate_inventory_availability(
            sales_order.source_store.byd_cost_center_code, 
            items_to_validate
        ):
            return APIResponse("Insufficient inventory for some items.", status.HTTP_400_BAD_REQUEST)
        
        # Create goods issue note
        goods_issue = GoodsIssueNote()
        goods_issue.sales_order = sales_order
        goods_issue.source_store = sales_order.source_store
        goods_issue.created_by = request.user
        goods_issue = goods_issue.save(issue_data=validated_data)
        
        serializer = GoodsIssueNoteSerializer(goods_issue, context={'request': request})
        return APIResponse("Goods Issue Created", status.HTTP_201_CREATED, data=serializer.data)
    
    except SalesOrder.DoesNotExist:
        return APIResponse("Sales order not found.", status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logging.error(f"Error creating goods issue: {e}")
        return APIResponse(str(e), status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_goods_issues(request):
    """
    Get all goods issue notes for user's authorized stores
    """
    try:
        user_stores = auth_service.get_user_authorized_stores(request.user)
        
        goods_issues = GoodsIssueNote.objects.filter(
            source_store__in=user_stores
        ).order_by('-created_date')
        
        if goods_issues.exists():
            # Paginate the results
            paginated = paginator.paginate_queryset(goods_issues, request)
            serializer = GoodsIssueNoteSerializer(paginated, many=True, context={'request': request})
            paginated_data = paginator.get_paginated_response(serializer.data).data
            return APIResponse("Goods Issues Retrieved", status.HTTP_200_OK, data=paginated_data)
        
        return APIResponse("No goods issues found for your stores.", status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        logging.error(f"Error retrieving goods issues: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_goods_issue(request, issue_number):
    """
    Get a specific goods issue note
    """
    try:
        user_stores = auth_service.get_user_authorized_stores(request.user)
        
        goods_issue = GoodsIssueNote.objects.get(
            issue_number=issue_number,
            source_store__in=user_stores
        )
        
        serializer = GoodsIssueNoteSerializer(goods_issue, context={'request': request})
        return APIResponse("Goods Issue Retrieved", status.HTTP_200_OK, data=serializer.data)
    
    except GoodsIssueNote.DoesNotExist:
        return APIResponse("Goods issue not found.", status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logging.error(f"Error retrieving goods issue {issue_number}: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([CombinedAuthentication])
def create_transfer_receipt(request):
    """
    Create a transfer receipt note
    """
    try:
        serializer = CreateTransferReceiptSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse("Invalid input data.", status.HTTP_400_BAD_REQUEST,
                             data=serializer.errors)
        
        validated_data = serializer.validated_data
        goods_issue_number = validated_data['goods_issue_number']
        
        # Get the goods issue note
        goods_issue = GoodsIssueNote.objects.get(issue_number=goods_issue_number)
        
        # Check if user has access to destination store
        destination_store = goods_issue.sales_order.destination_store
        if not auth_service.validate_store_access(request.user, destination_store.id):
            return APIResponse("You don't have access to the destination store.", status.HTTP_403_FORBIDDEN)
        
        # Create transfer receipt note
        transfer_receipt = TransferReceiptNote()
        transfer_receipt.goods_issue = goods_issue
        transfer_receipt.destination_store = destination_store
        transfer_receipt.created_by = request.user
        transfer_receipt = transfer_receipt.save(receipt_data=validated_data)
        
        serializer = TransferReceiptNoteSerializer(transfer_receipt, context={'request': request})
        return APIResponse("Transfer Receipt Created", status.HTTP_201_CREATED, data=serializer.data)
    
    except GoodsIssueNote.DoesNotExist:
        return APIResponse("Goods issue note not found.", status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logging.error(f"Error creating transfer receipt: {e}")
        return APIResponse(str(e), status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_transfer_receipts(request):
    """
    Get all transfer receipt notes for user's authorized stores
    """
    try:
        user_stores = auth_service.get_user_authorized_stores(request.user)
        
        transfer_receipts = TransferReceiptNote.objects.filter(
            destination_store__in=user_stores
        ).order_by('-created_date')
        
        if transfer_receipts.exists():
            # Paginate the results
            paginated = paginator.paginate_queryset(transfer_receipts, request)
            serializer = TransferReceiptNoteSerializer(paginated, many=True, context={'request': request})
            paginated_data = paginator.get_paginated_response(serializer.data).data
            return APIResponse("Transfer Receipts Retrieved", status.HTTP_200_OK, data=paginated_data)
        
        return APIResponse("No transfer receipts found for your stores.", status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        logging.error(f"Error retrieving transfer receipts: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_transfer_receipt(request, receipt_number):
    """
    Get a specific transfer receipt note
    """
    try:
        user_stores = auth_service.get_user_authorized_stores(request.user)
        
        transfer_receipt = TransferReceiptNote.objects.get(
            receipt_number=receipt_number,
            destination_store__in=user_stores
        )
        
        serializer = TransferReceiptNoteSerializer(transfer_receipt, context={'request': request})
        return APIResponse("Transfer Receipt Retrieved", status.HTTP_200_OK, data=serializer.data)
    
    except TransferReceiptNote.DoesNotExist:
        return APIResponse("Transfer receipt not found.", status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logging.error(f"Error retrieving transfer receipt {receipt_number}: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_pending_issues(request):
    """
    Get sales orders that are pending goods issue for user's source stores
    """
    try:
        user_stores = auth_service.get_user_authorized_stores(request.user)
        
        # Get sales orders where user's stores are source stores and not fully issued
        pending_orders = SalesOrder.objects.filter(
            source_store__in=user_stores,
            delivery_status_code__in=['1', '2']  # Not delivered or partially delivered
        ).order_by('-order_date')
        
        if pending_orders.exists():
            # Paginate the results
            paginated = paginator.paginate_queryset(pending_orders, request)
            serializer = SalesOrderSerializer(paginated, many=True, context={'request': request})
            paginated_data = paginator.get_paginated_response(serializer.data).data
            return APIResponse("Pending Issues Retrieved", status.HTTP_200_OK, data=paginated_data)
        
        return APIResponse("No pending issues found for your stores.", status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        logging.error(f"Error retrieving pending issues: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_pending_receipts(request):
    """
    Get goods issues that are pending receipt for user's destination stores
    """
    try:
        user_stores = auth_service.get_user_authorized_stores(request.user)
        
        # Get goods issues where user's stores are destination stores and not fully received
        pending_issues = GoodsIssueNote.objects.filter(
            sales_order__destination_store__in=user_stores
        ).exclude(
            # Exclude those that are fully received
            receipts__line_items__quantity_received__gte=F('line_items__quantity_issued')
        ).order_by('-created_date')
        
        if pending_issues.exists():
            # Paginate the results
            paginated = paginator.paginate_queryset(pending_issues, request)
            serializer = GoodsIssueNoteSerializer(paginated, many=True, context={'request': request})
            paginated_data = paginator.get_paginated_response(serializer.data).data
            return APIResponse("Pending Receipts Retrieved", status.HTTP_200_OK, data=paginated_data)
        
        return APIResponse("No pending receipts found for your stores.", status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        logging.error(f"Error retrieving pending receipts: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_transfer_summary(request):
    """
    Get transfer summary statistics for user's authorized stores
    """
    try:
        user_stores = auth_service.get_user_authorized_stores(request.user)
        
        summary_data = []
        for store in user_stores:
            # Calculate statistics for each store
            outbound_orders = SalesOrder.objects.filter(source_store=store).count()
            inbound_orders = SalesOrder.objects.filter(destination_store=store).count()
            
            pending_issues = SalesOrder.objects.filter(
                source_store=store,
                delivery_status_code__in=['1', '2']
            ).count()
            
            pending_receipts = GoodsIssueNote.objects.filter(
                sales_order__destination_store=store
            ).exclude(
                receipts__line_items__quantity_received__gte=F('line_items__quantity_issued')
            ).count()
            
            total_issued = GoodsIssueNote.objects.filter(
                source_store=store
            ).aggregate(
                total=Sum('line_items__quantity_issued')
            )['total'] or 0
            
            total_received = TransferReceiptNote.objects.filter(
                destination_store=store
            ).aggregate(
                total=Sum('line_items__quantity_received')
            )['total'] or 0
            
            summary_data.append({
                'store': store,
                'total_outbound_orders': outbound_orders,
                'total_inbound_orders': inbound_orders,
                'pending_issues': pending_issues,
                'pending_receipts': pending_receipts,
                'total_value_issued': total_issued,
                'total_value_received': total_received
            })
        
        from .serializers import StoreTransferSummarySerializer
        serializer = StoreTransferSummarySerializer(summary_data, many=True)
        return APIResponse("Transfer Summary Retrieved", status.HTTP_200_OK, data=serializer.data)
    
    except Exception as e:
        logging.error(f"Error retrieving transfer summary: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_user_store_authorizations(request):
    """
    Get store authorizations for the current user
    """
    try:
        authorizations = StoreAuthorization.objects.filter(user=request.user)
        
        if authorizations.exists():
            serializer = StoreAuthorizationSerializer(authorizations, many=True)
            return APIResponse("Store Authorizations Retrieved", status.HTTP_200_OK, data=serializer.data)
        
        return APIResponse("No store authorizations found for user.", status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        logging.error(f"Error retrieving store authorizations: {e}")
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)