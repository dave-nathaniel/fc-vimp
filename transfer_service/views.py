from django.shortcuts import render
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum
from .models import SalesOrder, GoodsIssueNote, TransferReceiptNote, StoreAuthorization
from .serializers import (
    SalesOrderSerializer, GoodsIssueNoteSerializer, TransferReceiptNoteSerializer,
    GoodsIssueNoteCreateSerializer, TransferReceiptNoteCreateSerializer
)
from .services import AuthorizationService
import logging

logger = logging.getLogger(__name__)

# Create your views here.

class SalesOrderListView(generics.ListAPIView):
    queryset = SalesOrder.objects.all()
    serializer_class = SalesOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

class SalesOrderDetailView(generics.RetrieveAPIView):
    queryset = SalesOrder.objects.all()
    serializer_class = SalesOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

class GoodsIssueNoteListView(generics.ListAPIView):
    queryset = GoodsIssueNote.objects.all()
    serializer_class = GoodsIssueNoteSerializer
    permission_classes = [permissions.IsAuthenticated]

class GoodsIssueNoteDetailView(generics.RetrieveAPIView):
    queryset = GoodsIssueNote.objects.all()
    serializer_class = GoodsIssueNoteSerializer
    permission_classes = [permissions.IsAuthenticated]

class TransferReceiptNoteListView(generics.ListAPIView):
    queryset = TransferReceiptNote.objects.all()
    serializer_class = TransferReceiptNoteSerializer
    permission_classes = [permissions.IsAuthenticated]

class TransferReceiptNoteDetailView(generics.RetrieveAPIView):
    queryset = TransferReceiptNote.objects.all()
    serializer_class = TransferReceiptNoteSerializer
    permission_classes = [permissions.IsAuthenticated]


def check_inventory_availability(store_id, line_items):
    """
    Placeholder function for ICG inventory availability checking
    This will be implemented when ICG integration is added
    """
    # For now, return True as placeholder
    # In real implementation, this would check ICG inventory levels
    logger.info(f"Checking inventory availability for store {store_id}")
    
    # Simulate inventory check
    for item in line_items:
        product_id = item['sales_order_line_item'].product_id
        quantity = item['quantity_issued']
        logger.info(f"Checking availability: Product {product_id}, Quantity {quantity}")
        
        # Placeholder: assume inventory is available
        # Real implementation would call ICG API
    
    return True


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


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_goods_issue(request):
    """
    Create a goods issue note with validation, inventory checking, and notifications
    """
    try:
        with transaction.atomic():
            # Validate input data using serializer
            serializer = GoodsIssueNoteCreateSerializer(
                data=request.data, 
                context={'request': request}
            )
            
            if not serializer.is_valid():
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'error_code': 'VALIDATION_ERROR',
                    'details': {
                        'field_errors': serializer.errors,
                        'validation_errors': []
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Extract validated data
            validated_data = serializer.validated_data
            sales_order = validated_data['sales_order']
            source_store = validated_data['source_store']
            line_items = validated_data['line_items']
            
            # Additional store authorization validation
            auth_service = AuthorizationService()
            if not auth_service.validate_store_access(request.user, source_store.id):
                return Response({
                    'success': False,
                    'message': 'You are not authorized to create goods issues for this store',
                    'error_code': 'AUTHORIZATION_ERROR',
                    'details': {
                        'field_errors': {},
                        'validation_errors': ['Store authorization failed']
                    }
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check inventory availability (placeholder for ICG integration)
            if not check_inventory_availability(source_store.id, line_items):
                return Response({
                    'success': False,
                    'message': 'Insufficient inventory available for goods issue',
                    'error_code': 'INVENTORY_INSUFFICIENT',
                    'details': {
                        'field_errors': {},
                        'validation_errors': ['Inventory availability check failed']
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Create the goods issue note
            goods_issue = serializer.save()
            
            # Send email notification to destination store manager
            notification_sent = send_goods_issue_notification(goods_issue)
            if not notification_sent:
                logger.warning(f"Failed to send notification for goods issue {goods_issue.issue_number}")
            
            # Trigger async tasks for external system integration
            goods_issue.post_to_icg()  # Post to ICG inventory system
            goods_issue.post_to_sap()  # Post to SAP ByD
            
            # Return success response with created goods issue data
            response_serializer = GoodsIssueNoteSerializer(goods_issue)
            return Response({
                'success': True,
                'message': f'Goods issue GI-{goods_issue.issue_number} created successfully',
                'data': response_serializer.data,
                'notification_sent': notification_sent
            }, status=status.HTTP_201_CREATED)
            
    except ValidationError as e:
        return Response({
            'success': False,
            'message': 'Validation error occurred',
            'error_code': 'VALIDATION_ERROR',
            'details': {
                'field_errors': {},
                'validation_errors': [str(e)]
            }
        }, status=status.HTTP_400_BAD_REQUEST)
        
    except Exception as e:
        logger.error(f"Error creating goods issue: {str(e)}")
        return Response({
            'success': False,
            'message': 'An error occurred while creating the goods issue',
            'error_code': 'INTERNAL_ERROR',
            'details': {
                'field_errors': {},
                'validation_errors': [str(e)]
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_transfer_receipt(request):
    """
    Create a transfer receipt note with validation, authorization checks, and notifications
    """
    try:
        with transaction.atomic():
            # Validate input data using serializer
            serializer = TransferReceiptNoteCreateSerializer(
                data=request.data,
                context={'request': request}
            )
            
            if not serializer.is_valid():
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'error_code': 'VALIDATION_ERROR',
                    'details': {
                        'field_errors': serializer.errors,
                        'validation_errors': []
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Extract validated data
            validated_data = serializer.validated_data
            goods_issue = validated_data['goods_issue']
            destination_store = validated_data['destination_store']
            line_items = validated_data['line_items']
            
            # Additional store authorization validation
            auth_service = AuthorizationService()
            if not auth_service.validate_store_access(request.user, destination_store.id):
                return Response({
                    'success': False,
                    'message': 'You are not authorized to create transfer receipts for this store',
                    'error_code': 'AUTHORIZATION_ERROR',
                    'details': {
                        'field_errors': {},
                        'validation_errors': ['Store authorization failed']
                    }
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Validate against corresponding goods issue
            if destination_store != goods_issue.sales_order.destination_store:
                return Response({
                    'success': False,
                    'message': 'Destination store must match the sales order destination store',
                    'error_code': 'STORE_MISMATCH',
                    'details': {
                        'field_errors': {},
                        'validation_errors': ['Store mismatch with goods issue']
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate that goods issue line items belong to the goods issue
            for item_data in line_items:
                gi_line_item = item_data['goods_issue_line_item']
                if gi_line_item.goods_issue != goods_issue:
                    return Response({
                        'success': False,
                        'message': f'Line item {gi_line_item.id} does not belong to goods issue {goods_issue.id}',
                        'error_code': 'LINE_ITEM_MISMATCH',
                        'details': {
                            'field_errors': {},
                            'validation_errors': ['Line item mismatch with goods issue']
                        }
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Validate quantity doesn't exceed issued quantity
                existing_received = gi_line_item.transfer_receipt_items.aggregate(
                    total=Sum('quantity_received')
                )['total'] or 0
                
                total_to_receive = float(existing_received) + float(item_data['quantity_received'])
                
                if total_to_receive > float(gi_line_item.quantity_issued):
                    return Response({
                        'success': False,
                        'message': f'Cannot receive {item_data["quantity_received"]} for product {gi_line_item.product_name}. Available: {float(gi_line_item.quantity_issued) - float(existing_received)}',
                        'error_code': 'QUANTITY_EXCEEDED',
                        'details': {
                            'field_errors': {},
                            'validation_errors': ['Received quantity exceeds issued quantity']
                        }
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Create the transfer receipt note
            transfer_receipt = serializer.save()
            
            # Send email notifications
            notification_sent = send_transfer_receipt_notification(transfer_receipt)
            if not notification_sent:
                logger.warning(f"Failed to send notifications for transfer receipt {transfer_receipt.receipt_number}")
            
            # Trigger async tasks for external system integration
            transfer_receipt.update_destination_inventory()  # Update ICG inventory
            transfer_receipt.complete_transfer_in_sap()  # Update SAP ByD status
            
            # Return success response with created transfer receipt data
            response_serializer = TransferReceiptNoteSerializer(transfer_receipt)
            return Response({
                'success': True,
                'message': f'Transfer receipt TR-{transfer_receipt.receipt_number} created successfully',
                'data': response_serializer.data,
                'notification_sent': notification_sent
            }, status=status.HTTP_201_CREATED)
            
    except ValidationError as e:
        return Response({
            'success': False,
            'message': 'Validation error occurred',
            'error_code': 'VALIDATION_ERROR',
            'details': {
                'field_errors': {},
                'validation_errors': [str(e)]
            }
        }, status=status.HTTP_400_BAD_REQUEST)
        
    except Exception as e:
        logger.error(f"Error creating transfer receipt: {str(e)}")
        return Response({
            'success': False,
            'message': 'An error occurred while creating the transfer receipt',
            'error_code': 'INTERNAL_ERROR',
            'details': {
                'field_errors': {},
                'validation_errors': [str(e)]
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)