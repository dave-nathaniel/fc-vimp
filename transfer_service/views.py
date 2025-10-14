from django.shortcuts import render
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.exceptions import PermissionDenied
from byd_service.rest import RESTServices
from overrides.authenticate import CombinedAuthentication
from overrides.rest_framework import APIResponse, CustomPagination
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum, Q
from .models import StoreAuthorization, InboundDelivery
from .serializers import (
	TransferReceiptNoteSerializer,InboundDeliverySerializer
)
from .services import AuthorizationService
from .validators import (
	ValidationErrorResponse, TransferReceiptValidator,
	StoreAuthorizationValidator
)
import logging

logger = logging.getLogger(__name__)

# Create your views here.

@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_inbound_deliveries(request):
	"""
		List inbound deliveries for the authenticated user's authorized stores
		Supports searching by delivery ID and pagination
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
			
		# Order queryset
		queryset = queryset.order_by('-created_date')
		
		# Apply pagination
		paginator = CustomPagination()
		paginated_queryset = paginator.paginate_queryset(queryset, request)
		serializer = InboundDeliverySerializer(paginated_queryset, many=True)
		
		return APIResponse(
			status=status.HTTP_200_OK,
			message='Inbound deliveries fetched successfully',
			data=paginator.get_paginated_response(serializer.data).data
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
		Search in the local database for deliveries using any of the following parameters:
			delivery_id
			source_location_id
			source_location_name
			destination_store
			delivery_date
			delivery_status_code
			delivery_type_code
			sales_order_reference
	"""
	
	user = request.user
	authorized_stores = AuthorizationService.get_user_authorized_stores(user)
	queryset = InboundDelivery.objects.filter(destination_store__in=authorized_stores)

	delivery_id = request.query_params.get('delivery_id')
	source_location_id = request.query_params.get('source_location_id')
	source_location_name = request.query_params.get('source_location_name')
	destination_store = request.query_params.get('destination_store')
	delivery_date = request.query_params.get('delivery_date')
	delivery_status_code = request.query_params.get('delivery_status_code')
	delivery_type_code = request.query_params.get('delivery_type_code')
	sales_order_reference = request.query_params.get('sales_order_reference')

	if not any([
		delivery_id, 
		source_location_id, 
		source_location_name, 
		destination_store, 
		delivery_date, 
		delivery_status_code, 
		delivery_type_code, 
		sales_order_reference
	]):
		return APIResponse(
			status=status.HTTP_400_BAD_REQUEST,
			message='At least one parameter is required'
		)
	
	try:
		# First check local database
		filter_kwargs = {
			'destination_store__in': authorized_stores  # Always apply store authorization filter
		}
		
		# Only add filters for parameters that are provided
		if delivery_id:
			filter_kwargs['delivery_id__icontains'] = delivery_id
		if source_location_id:
			filter_kwargs['source_location_id__icontains'] = source_location_id
		if source_location_name:
			filter_kwargs['source_location_name__icontains'] = source_location_name
		if delivery_date:
			filter_kwargs['delivery_date__icontains'] = delivery_date
		if delivery_status_code:
			filter_kwargs['delivery_status_code__icontains'] = delivery_status_code
		if delivery_type_code:
			filter_kwargs['delivery_type_code__icontains'] = delivery_type_code
		if sales_order_reference:
			filter_kwargs['sales_order_reference__icontains'] = sales_order_reference
			
		results = InboundDelivery.objects.filter(**filter_kwargs)
		
		# Apply pagination to the results
		paginator = CustomPagination()
		paginated_results = paginator.paginate_queryset(results, request)
		# serialize
		serializer = InboundDeliverySerializer(paginated_results, many=True)
		
		return APIResponse(
			status=status.HTTP_200_OK,
			message='Inbound deliveries fetched successfully',
			data=paginator.get_paginated_response(serializer.data).data
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
			# Get inbound delivery and authorize
			inbound_delivery_id = request.data.get('delivery')
			if not inbound_delivery_id:
				return APIResponse(
					status=status.HTTP_400_BAD_REQUEST,
					message='delivery is required'
				)
			try:
				inbound_delivery = InboundDelivery.objects.get(id=inbound_delivery_id)
			except InboundDelivery.DoesNotExist:
				return APIResponse(
					status=status.HTTP_404_NOT_FOUND,
					message='Inbound delivery not found'
				)
			# Authorization: user must have access to destination store
			if not AuthorizationService.validate_store_access(request.user, inbound_delivery.destination_store.byd_cost_center_code):
				return APIResponse(
					status=status.HTTP_403_FORBIDDEN,
					message=f"You are not authorized to receive inbound deliveries for store '{inbound_delivery.destination_store.store_name}'"
				)
			# Validate delivery status
			if inbound_delivery.delivery_status_code not in ['1', '2']:
				return APIResponse(
					status=status.HTTP_400_BAD_REQUEST,
					message=f"Cannot receive from inbound delivery in status: {inbound_delivery.delivery_status}"
				)
			# Validate input data using serializer with request context
			serializer = TransferReceiptNoteSerializer(data=request.data, context={'request': request})
			if not serializer.is_valid():
				return APIResponse(
					status=status.HTTP_400_BAD_REQUEST,
					message='Validation error',
					data=serializer.errors
				)
			# Create receipt and update inbound delivery via serializer
			receipt = serializer.save()
			response_serializer = TransferReceiptNoteSerializer(receipt)
			send_inbound_delivery_receipt_notification(inbound_delivery, receipt.line_items.all(), request.user, receipt.notes)
			return APIResponse(
				message=f"Transfer receipt TR-{receipt.receipt_number} created successfully",
				status=status.HTTP_201_CREATED,
				data=response_serializer.data
			)
	except ValidationError as e:
		logger.error(f"Validation error creating transfer receipt: {str(e)}")
		return APIResponse(
			status=status.HTTP_400_BAD_REQUEST,
			message='Validation error',
			data={'non_field_errors': [str(e)]}
		)
	except Exception as e:
		logger.error(f"Unexpected error creating transfer receipt: {str(e)}")
		return APIResponse(
			status=status.HTTP_500_INTERNAL_SERVER_ERROR,
			message=f"An error occurred while creating the transfer receipt: {str(e)}"
		)


def send_inbound_delivery_receipt_notification(inbound_delivery, received_items, user, notes):
	"""
	Send email notification about delivery receipt creation
	"""
	try:
		# For warehouse-to-store transfers, notify destination store managers
		# and potentially warehouse managers (if StoreAuthorization exists for warehouse)
		destination_store = inbound_delivery.destination_store
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
			'inbound_delivery': inbound_delivery,
			'received_items': received_items,
			'received_by': user,
			'notes': notes,
			'destination_store': inbound_delivery.destination_store
		}
		
		# Render email content
		subject = f"Delivery Received - {inbound_delivery.delivery_id}"
		html_content = render_to_string('transfer_service/delivery_receipt_notification.html', context)

		# Send email
		email = EmailMessage(
			subject=subject,
			body=html_content,
			from_email='network@foodconceptsplc.com',
			to=["davynathaniel@gmail.com"],
		)
		email.content_subtype = 'html'
		email.send()
		
		logger.info(f"Delivery receipt notification sent for inbound delivery {inbound_delivery.delivery_id}")
		return True
		
	except Exception as e:
		logger.error(f"Error sending inbound delivery receipt notification: {str(e)}")
		return False