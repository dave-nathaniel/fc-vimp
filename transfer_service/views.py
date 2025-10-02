from django.shortcuts import render
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.exceptions import PermissionDenied
from byd_service.rest import RESTServices
from overrides.authenticate import CombinedAuthentication
from overrides.rest_framework import APIResponse
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum, Q
from .models import SalesOrder, GoodsIssueNote, TransferReceiptNote, StoreAuthorization, InboundDelivery
from .serializers import (
    SalesOrderSerializer, GoodsIssueNoteSerializer, TransferReceiptNoteSerializer,
    GoodsIssueNoteCreateSerializer, TransferReceiptNoteCreateSerializer,
    InboundDeliverySerializer, DeliveryReceiptSerializer
)
from .services import AuthorizationService
from .validators import (
    ValidationErrorResponse, GoodsIssueValidator, TransferReceiptValidator,
    StoreAuthorizationValidator, InventoryValidator
)
import logging

logger = logging.getLogger(__name__)

# Create your views here.

@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_inbound_deliveries(request):
    """
    List inbound deliveries for the authenticated user's authorized stores
    Supports searching by delivery ID
    """
    try:
        user = request.user
        # Filter deliveries by user's authorized stores (as destination stores)
        authorized_stores = AuthorizationService.get_user_authorized_stores(user)
        queryset = InboundDelivery.objects.filter(destination_store__in=authorized_stores)
        
        # Support search by delivery ID
        delivery_id = request.query_params.get('delivery_id')
        if delivery_id:
            queryset = queryset.filter(delivery_id__icontains=delivery_id)
        
        # Support filtering by status
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(delivery_status_code=status_filter)
        
        return APIResponse(
            status=status.HTTP_200_OK,
            message='Inbound deliveries fetched successfully',
            data=InboundDeliverySerializer(queryset.order_by('-created_date'), many=True).data
        )
    except Exception as e:
        logger.error(f"Error fetching inbound deliveries: {e}")
        return APIResponse(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message='Internal server error while fetching inbound deliveries'
        )


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_inbound_delivery(request, pk):
    """
    Get details of a specific inbound delivery
    If not found locally, try to fetch from SAP ByD
    """
    try:
        try:
            # Check if delivery exists locally
            delivery = InboundDelivery.objects.get(delivery_id=pk)
        except InboundDelivery.DoesNotExist:
            # If not found locally, try to fetch from SAP ByD
            byd_rest = RESTServices()
            delivery_data = byd_rest.get_delivery_by_id(pk)
            if not delivery_data:
                return APIResponse(
                    status=status.HTTP_404_NOT_FOUND,
                    message=f"Delivery {pk} not found in SAP ByD"
                )
            # Create local delivery record
            delivery = InboundDelivery.create_from_byd_data(delivery_data)

        # Check user authorization for the delivery's destination store
        if not AuthorizationService.validate_store_access(request.user, delivery.destination_store.byd_cost_center_code):
            return APIResponse(
                status=status.HTTP_403_FORBIDDEN,
                message="You are not authorized to access this delivery"
            )
        # Return the delivery data
        return APIResponse(
            status=status.HTTP_200_OK,
            message="Delivery fetched successfully",
            data=InboundDeliverySerializer(delivery).data
        )
    except Exception as e:
        logger.error(f"Error fetching delivery {pk}: {e}")
        return APIResponse(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f"Error fetching delivery {pk}: {e}"
        )


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def search_deliveries(request):
    """
    Search for deliveries by delivery ID across SAP ByD and local database
    """
    delivery_id = request.query_params.get('delivery_id')
    if not delivery_id:
        return APIResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message='delivery_id parameter is required'
        )
    
    user = request.user
    authorized_stores = AuthorizationService.get_user_authorized_stores(user)
    authorized_byd_cost_center_codes = [store.byd_cost_center_code for store in authorized_stores]
    
    try:
        # First check local database
        local_deliveries = InboundDelivery.objects.filter(
            delivery_id__icontains=delivery_id,
            destination_store__in=authorized_stores
        )
        
        results = []
        for delivery in local_deliveries:
            serializer = InboundDeliverySerializer(delivery)
            results.append({
                'source': 'local',
                'delivery': serializer.data
            })
        
        # If no local results, search SAP ByD
        if not results:
            from byd_service.rest import RESTServices
            byd_rest = RESTServices()
            
            # Search across all authorized stores
            for byd_cost_center_code in authorized_byd_cost_center_codes:
                try:
                    byd_deliveries = byd_rest.search_deliveries_by_store(byd_cost_center_code)
                    matching_deliveries = [
                        d for d in byd_deliveries 
                        if delivery_id.lower() in d.get('ID', '').lower()
                    ]
                    
                    for delivery_data in matching_deliveries:
                        results.append({
                            'source': 'sap_byd',
                            'delivery': {
                                'delivery_id': delivery_data.get('ID'),
                                'object_id': delivery_data.get('ObjectID'),
                                'delivery_date': delivery_data.get('PlannedDeliveryDate') or delivery_data.get('ActualDeliveryDate'),
                                'status': delivery_data.get('DeliveryProcessingStatusCode'),
                                'sales_order_reference': delivery_data.get('SalesOrderID')
                            }
                        })
                        
                except Exception as e:
                    logger.warning(f"Error searching deliveries for store {byd_cost_center_code}: {e}")
                    continue
        
        return APIResponse(
            status=status.HTTP_200_OK,
            message='Deliveries fetched successfully',
            data={
                'results': results,
                'total_count': len(results)
            }
        )
        
    except Exception as e:
        logger.error(f"Error searching deliveries: {e}")
        return APIResponse(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message='Internal server error while searching deliveries'
        )


@api_view(['POST'])
@authentication_classes([CombinedAuthentication])
def create_delivery_receipt(request):
    """
    Create a delivery receipt from an inbound delivery with comprehensive validation
    """
    try:
        with transaction.atomic():
            # Validate input data using serializer
            serializer = DeliveryReceiptSerializer(data=request.data)
            
            if not serializer.is_valid():
                return APIResponse(
                    status=status.HTTP_400_BAD_REQUEST,
                    message='Validation error',
                    data=serializer.errors
                )
            
            # Extract validated data
            validated_data = serializer.validated_data
            delivery = validated_data['delivery']
            line_items = validated_data['line_items']
            notes = validated_data.get('notes', '')
            
            # Enhanced store authorization validation
            try:
                print(request.user)
                print(delivery.destination_store.byd_cost_center_code)
                StoreAuthorizationValidator.validate_store_access(
                    request.user, 
                    delivery.destination_store.byd_cost_center_code,
                    # required_roles=['manager', 'assistant', 'clerk']
                )
            except ValidationError as e:
                return APIResponse(
                    status=status.HTTP_403_FORBIDDEN,
                    message=f"You are not authorized to receive deliveries for store '{delivery.destination_store.store_name}'"
                )
            
            # Validate that delivery is in the correct status
            if delivery.delivery_status_code not in ['1', '2']:  # Open or In Process
                return APIResponse(
                    status=status.HTTP_400_BAD_REQUEST,
                    message=f"Cannot receive from delivery in status: {delivery.delivery_status}"
                )
            
            # Update delivery line items with received quantities
            updated_items = []
            for item_data in line_items:
                delivery_line_item = item_data['delivery_line_item']
                quantity_received = item_data['quantity_received']
                
                # Update the received quantity
                old_quantity = delivery_line_item.quantity_received
                delivery_line_item.quantity_received += quantity_received
                delivery_line_item.save()
                
                updated_items.append({
                    'product_id': delivery_line_item.product_id,
                    'product_name': delivery_line_item.product_name,
                    'quantity_received': quantity_received,
                    'total_received': delivery_line_item.quantity_received,
                    'quantity_expected': delivery_line_item.quantity_expected
                })
            
            # Update delivery status
            if delivery.is_fully_received:
                delivery.delivery_status_code = '3'  # Completed
            else:
                delivery.delivery_status_code = '2'  # In Process
            delivery.save()
            
            # TODO: Update inventory in ICG (async)
            
            # Send notification to source store
            try:
                send_delivery_receipt_notification(delivery, updated_items, request.user, notes)
            except Exception as e:
                logger.warning(f"Failed to send delivery receipt notification: {e}")
            
            # Return success response with updated delivery
            response_serializer = InboundDeliverySerializer(delivery)
            return APIResponse(
                message=f'Delivery receipt created successfully for delivery {delivery.delivery_id}',
                status=status.HTTP_201_CREATED,
                data={
                    'delivery': response_serializer.data,
                    'received_items': updated_items,
                    'notes': notes
                }
            )
            
    except ValidationError as e:
        logger.error(f"Validation error creating delivery receipt: {str(e)}")
        return APIResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message='Validation error',
            data={'non_field_errors': [str(e)]}
        )
    except Exception as e:
        logger.error(f"Unexpected error creating delivery receipt: {str(e)}")
        return APIResponse(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f"An error occurred while creating the delivery receipt: {str(e)}"
        )


def send_delivery_receipt_notification(delivery, received_items, user, notes):
    """
    Send email notification about delivery receipt creation
    """
    try:
        # For warehouse-to-store transfers, notify destination store managers
        # and potentially warehouse managers (if StoreAuthorization exists for warehouse)
        destination_store = delivery.destination_store
        destination_managers = StoreAuthorization.objects.filter(
            store=destination_store,
            role__in=['manager', 'assistant']
        ).select_related('user')
        
        manager_emails = [
            auth.user.email for auth in destination_managers 
            if auth.user.email
        ]
        
        if not manager_emails:
            logger.warning(f"No email addresses found for managers of store {destination_store.store_name}")
            return False
        
        # Prepare email context
        context = {
            'delivery': delivery,
            'received_items': received_items,
            'received_by': user,
            'notes': notes,
            'destination_store': delivery.destination_store
        }
        
        # Render email content
        subject = f"Delivery Received - {delivery.delivery_id}"
        html_content = render_to_string('transfer_service/delivery_receipt_notification.html', context)
        
        # Send email
        email = EmailMessage(
            subject=subject,
            body=html_content,
            from_email='noreply@foodconcepts.ng',
            to=manager_emails,
        )
        email.content_subtype = 'html'
        email.send()
        
        logger.info(f"Delivery receipt notification sent for delivery {delivery.delivery_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending delivery receipt notification: {str(e)}")
        return False


def send_goods_issue_notification(goods_issue):
    """
    Send email notification to destination store manager about goods issue
    """
    try:
        # Get destination store managers
        destination_store = goods_issue.sales_order.destination_store
        store_managers = StoreAuthorization.objects.filter(
            store=destination_store,
            role__in=['manager', 'assistant']
        ).select_related('user')
        
        if not store_managers:
            logger.warning(f"No store managers found for destination store {destination_store.id}")
            return False
        
        # Prepare email data
        email_data = {
            'goods_issue': goods_issue,
            'sales_order': goods_issue.sales_order,
            'source_store': goods_issue.source_store,
            'destination_store': destination_store,
            'line_items': goods_issue.line_items.all(),
            'created_by': goods_issue.created_by
        }
        
        # Render email template
        html_content = render_to_string('transfer_service/goods_issue_notification.html', email_data)
        
        # Get manager email addresses
        manager_emails = [auth.user.email for auth in store_managers if auth.user.email]
        
        if not manager_emails:
            logger.warning(f"No email addresses found for store managers of {destination_store.store_name}")
            return False
        
        # Send email
        email = EmailMessage(
            subject=f'Goods Issue Created - GI-{goods_issue.issue_number}',
            body=html_content,
            from_email='network@foodconceptsplc.com',
            to=manager_emails,
        )
        email.content_subtype = 'html'
        email.send()
        
        logger.info(f"Goods issue notification sent for GI-{goods_issue.issue_number}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending goods issue notification: {str(e)}")
        return False


def send_transfer_receipt_notification(transfer_receipt):
    """
    Send email notification about transfer receipt creation
    """
    try:
        # Get source store managers for completion notification
        source_store = transfer_receipt.goods_issue.source_store
        source_managers = StoreAuthorization.objects.filter(
            store=source_store,
            role__in=['manager', 'assistant']
        ).select_related('user')
        
        # Get destination store managers for receipt confirmation
        destination_store = transfer_receipt.destination_store
        dest_managers = StoreAuthorization.objects.filter(
            store=destination_store,
            role__in=['manager', 'assistant']
        ).select_related('user')
        
        # Prepare email data
        email_data = {
            'transfer_receipt': transfer_receipt,
            'goods_issue': transfer_receipt.goods_issue,
            'sales_order': transfer_receipt.goods_issue.sales_order,
            'source_store': source_store,
            'destination_store': destination_store,
            'line_items': transfer_receipt.line_items.all(),
            'created_by': transfer_receipt.created_by
        }
        
        # Check for quantity variations
        has_variations = False
        for item in transfer_receipt.line_items.all():
            if item.quantity_received != item.goods_issue_line_item.quantity_issued:
                has_variations = True
                break
        
        email_data['has_variations'] = has_variations
        
        # Send completion notification to source store
        if source_managers:
            source_emails = [auth.user.email for auth in source_managers if auth.user.email]
            if source_emails:
                html_content = render_to_string('transfer_service/transfer_completion_notification.html', email_data)
                
                email = EmailMessage(
                    subject=f'Transfer Completed - TR-{transfer_receipt.receipt_number}',
                    body=html_content,
                    from_email='network@foodconceptsplc.com',
                    to=source_emails,
                )
                email.content_subtype = 'html'
                email.send()
                
                logger.info(f"Transfer completion notification sent for TR-{transfer_receipt.receipt_number}")
        
        # Send receipt confirmation to destination store
        if dest_managers:
            dest_emails = [auth.user.email for auth in dest_managers if auth.user.email]
            if dest_emails:
                html_content = render_to_string('transfer_service/transfer_receipt_notification.html', email_data)
                
                email = EmailMessage(
                    subject=f'Transfer Receipt Created - TR-{transfer_receipt.receipt_number}',
                    body=html_content,
                    from_email='network@foodconceptsplc.com',
                    to=dest_emails,
                )
                email.content_subtype = 'html'
                email.send()
                
                logger.info(f"Transfer receipt notification sent for TR-{transfer_receipt.receipt_number}")
        
        # Send quantity variation notification if needed
        if has_variations:
            all_managers = list(source_managers) + list(dest_managers)
            all_emails = [auth.user.email for auth in all_managers if auth.user.email]
            
            if all_emails:
                html_content = render_to_string('transfer_service/quantity_variation_notification.html', email_data)
                
                email = EmailMessage(
                    subject=f'Quantity Variation Alert - TR-{transfer_receipt.receipt_number}',
                    body=html_content,
                    from_email='network@foodconceptsplc.com',
                    to=all_emails,
                )
                email.content_subtype = 'html'
                email.send()
                
                logger.info(f"Quantity variation notification sent for TR-{transfer_receipt.receipt_number}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error sending transfer receipt notifications: {str(e)}")
        return False


    """
    Create a transfer receipt note with comprehensive validation, authorization checks, and notifications
    """
    try:
        with transaction.atomic():
            # Validate input data using serializer
            serializer = TransferReceiptNoteCreateSerializer(
                data=request.data,
                context={'request': request}
            )
            
            if not serializer.is_valid():
                return ValidationErrorResponse.create_validation_error_response(serializer.errors)
            
            # Extract validated data
            validated_data = serializer.validated_data
            goods_issue = validated_data['goods_issue']
            destination_store = validated_data['destination_store']
            line_items = validated_data['line_items']
            
            # Enhanced store authorization validation
            try:
                StoreAuthorizationValidator.validate_store_access(
                    request.user, 
                    destination_store.byd_cost_center_code,
                    required_roles=['manager', 'assistant']
                )
            except ValidationError as e:
                return ValidationErrorResponse.create_authorization_error_response(
                    f"You are not authorized to create transfer receipts for store '{destination_store.store_name}'"
                )
            
            # Comprehensive transfer receipt validation
            try:
                TransferReceiptValidator.validate_transfer_receipt_creation(
                    goods_issue, destination_store, line_items, request.user
                )
            except ValidationError as e:
                return ValidationErrorResponse.create_validation_error_response(e)
            
            # Create the transfer receipt note
            transfer_receipt = serializer.save()
            
            # Send email notifications
            # notification_sent = send_transfer_receipt_notification(transfer_receipt)
            # if not notification_sent:
            #     logger.warning(f"Failed to send notifications for transfer receipt {transfer_receipt.receipt_number}")
            
            # Trigger async tasks for external system integration
            try:
                transfer_receipt.update_destination_inventory()  # Update ICG inventory
                transfer_receipt.complete_transfer_in_sap()  # Update SAP ByD status
            except Exception as e:
                logger.error(f"Error posting transfer receipt to external systems: {str(e)}")
                # Don't fail the request, but log the error
            
            # Return success response with created transfer receipt data
            response_serializer = TransferReceiptNoteSerializer(transfer_receipt)
            return APIResponse(
                message=f'Transfer receipt TR-{transfer_receipt.receipt_number} created successfully',
                status=status.HTTP_201_CREATED,
                data=response_serializer.data,
                # 'notification_sent': notification_sent
            )
            
    except ValidationError as e:
        return ValidationErrorResponse.create_validation_error_response(e)
        
    except Exception as e:
        logger.error(f"Error creating transfer receipt: {str(e)}")
        return ValidationErrorResponse.create_internal_error_response(
            f"An error occurred while creating the transfer receipt: {str(e)}"
        )