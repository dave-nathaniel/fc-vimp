import logging
import os
import uuid
from datetime import date

import pandas as pd
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes

from byd_service.rest import RESTServices
from overrides.authenticate import CombinedAuthentication
from overrides.rest_framework import APIResponse, CustomPagination
from .models import StoreAuthorization, InboundDelivery
from .serializers import (
	TransferReceiptNoteSerializer,InboundDeliverySerializer
)
from .services import AuthorizationService

logger = logging.getLogger(__name__)

EXPORT_DOWNLOAD_DIR = 'downloads'
EXPORT_FILENAME_PREFIX = 'transfers_search'
EXPORT_COLUMNS = [
	'Delivery ID',
	'Source Location ID',
	'Source Location Name',
	'Destination Store Name',
	'Destination Store Code',
	'Delivery Date',
	'Delivery Status Code',
	'Delivery Status',
	'Delivery Type Code',
	'Sales Order Reference',
	'Created Date',
]


def _format_date(value):
	return value.isoformat() if value else ''


def _build_export_rows(queryset):
	rows = []
	for delivery in queryset:
		dest_store = getattr(delivery, 'destination_store', None)
		rows.append({
			'Delivery ID': delivery.delivery_id,
			'Source Location ID': delivery.source_location_id,
			'Source Location Name': delivery.source_location_name,
			'Destination Store Name': getattr(dest_store, 'store_name', ''),
			'Destination Store Code': getattr(dest_store, 'byd_cost_center_code', ''),
			'Delivery Date': _format_date(delivery.delivery_date),
			'Delivery Status Code': delivery.delivery_status_code,
			'Delivery Status': delivery.delivery_status,
			'Delivery Type Code': delivery.delivery_type_code,
			'Sales Order Reference': delivery.sales_order_reference or '',
			'Created Date': _format_date(delivery.created_date),
		})
	return rows


def _write_export_file(rows):
	download_root = os.path.join(settings.MEDIA_ROOT, EXPORT_DOWNLOAD_DIR)
	os.makedirs(download_root, exist_ok=True)
	timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
	filename = f"{EXPORT_FILENAME_PREFIX}_{timestamp}_{uuid.uuid4().hex[:8]}.xlsx"
	filepath = os.path.join(download_root, filename)

	df = pd.DataFrame(rows)
	if df.empty:
		df = pd.DataFrame(columns=EXPORT_COLUMNS)
	else:
		df = df.reindex(columns=EXPORT_COLUMNS)

	try:
		df.to_excel(filepath, index=False)
	except Exception as exc:
		logger.error(f"Failed to write delivery export to Excel: {exc}")
		raise

	return filename


def _normalize_media_url():
	media_url = settings.MEDIA_URL or 'media/'
	if not media_url.startswith('/'):
		media_url = f"/{media_url}"
	return media_url.rstrip('/')


def _generate_search_export_link(queryset, request):
	rows = _build_export_rows(queryset)
	filename = _write_export_file(rows)
	download_path = f"{_normalize_media_url()}/{EXPORT_DOWNLOAD_DIR}/{filename}"
	return request.build_absolute_uri(download_path)


def _apply_delivery_filters(queryset, query_params):
	"""
		Apply optional delivery filters based on request query parameters
	"""
	delivery_id = query_params.get('delivery_id')
	source_location_id = query_params.get('source_location_id')
	source_location_name = query_params.get('source_location_name')
	destination_store = query_params.get('destination_store')
	delivery_date = query_params.get('delivery_date')
	delivery_status_code = query_params.get('delivery_status_code') or query_params.get('status')
	delivery_type_code = query_params.get('delivery_type_code')
	sales_order_reference = query_params.get('sales_order_reference')

	if delivery_id:
		queryset = queryset.filter(delivery_id__icontains=delivery_id)
	if source_location_id:
		queryset = queryset.filter(source_location_id__icontains=source_location_id)
	if source_location_name:
		queryset = queryset.filter(source_location_name__icontains=source_location_name)
	if destination_store:
		queryset = queryset.filter(
			Q(destination_store__store_name__icontains=destination_store) |
			Q(destination_store__byd_cost_center_code__icontains=destination_store)
		)
	if delivery_date:
		try:
			parsed_date = date.fromisoformat(delivery_date)
		except ValueError:
			raise ValidationError("delivery_date must be in YYYY-MM-DD format")
		queryset = queryset.filter(delivery_date=parsed_date)
	if delivery_type_code:
		queryset = queryset.filter(delivery_type_code__icontains=delivery_type_code)
	if sales_order_reference:
		queryset = queryset.filter(sales_order_reference__icontains=sales_order_reference)
	if delivery_status_code:
		queryset = queryset.filter(delivery_status_code=delivery_status_code)

	return queryset

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
		
		try:
			queryset = _apply_delivery_filters(queryset, request.query_params)
		except ValidationError as e:
			return APIResponse(
				status=status.HTTP_400_BAD_REQUEST,
				message=str(e)
			)
			
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
		download - when set to true returns an Excel download URL for the filtered results.
		Pagination is applied even when no parameters are provided.
	"""
	
	user = request.user
	authorized_stores = AuthorizationService.get_user_authorized_stores(user)
	queryset = InboundDelivery.objects.filter(destination_store__in=authorized_stores)
	download_requested = request.query_params.get('download', '').lower() == 'true'

	try:
		try:
			queryset = _apply_delivery_filters(queryset, request.query_params)
		except ValidationError as e:
			return APIResponse(
				status=status.HTTP_400_BAD_REQUEST,
				message=str(e)
			)

		queryset = queryset.order_by('-created_date')
		download_url = None
		if download_requested:
			download_url = _generate_search_export_link(queryset, request)
		
		paginator = CustomPagination()
		paginated_results = paginator.paginate_queryset(queryset, request)
		serializer = InboundDeliverySerializer(paginated_results, many=True)

		paginated_data = paginator.get_paginated_response(serializer.data).data
		if download_url:
			paginated_data['download_url'] = download_url
		
		return APIResponse(
			status=status.HTTP_200_OK,
			message='Inbound deliveries fetched successfully',
			data=paginated_data
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