from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from egrn_service.models import GoodsReceivedNote, GoodsReceivedLineItem
from overrides.rest_framework import APIResponse
from overrides.rest_framework import CustomPagination
from core_service.cache_utils import CacheManager, get_or_set_cache, CachedPagination
from .models import Invoice
from .serializers import InvoiceSerializer, InvoiceLineItemSerializer

# Pagination
paginator = CustomPagination()

class VendorInvoiceView(APIView):
	"""
    Retrieve, update or delete a vendor invoice instance.
    """
	serializer_class = InvoiceSerializer
	permission_classes = (IsAuthenticated,)
	
	def get(self, request):
		# Generate cache key for this vendor's invoice query
		page = request.query_params.get('page', '1')
		page_size = request.query_params.get('size', '15')
		vendor_id = request.user.vendor_profile.id
		cache_key_suffix = f"vendor_invoices_{vendor_id}_page_{page}_size_{page_size}"
		
		# Get all invoices for the authenticated vendor with optimized queries
		invoices = Invoice.objects.select_related(
			'purchase_order',
			'purchase_order__vendor',
			'grn'
		).prefetch_related(
			'invoice_line_items__grn_line_item__purchase_order_line_item__delivery_store'
		).filter(purchase_order__vendor=request.user.vendor_profile)
		
		# Cache the total count for pagination
		total_count = CachedPagination.cache_page_count(invoices, cache_key_suffix)
		
		paginated = paginator.paginate_queryset(invoices, request, order_by='-date_created')
		invoices_serializer = InvoiceSerializer(paginated, many=True, context={'request':request})
		# Return the paginated response with the serialized GoodsReceivedNote instances
		paginated_data = paginator.get_paginated_response(invoices_serializer.data).data
		return APIResponse("Invoices Retrieved", status.HTTP_200_OK, data=paginated_data)
	
	def post(self, request):
		'''
			Takes a list of objects and Create Invoice and InvoiceLineItem objects from the request data.
		'''
		# The request must be a POST request
		request_data = request.data
		# Required fields
		required_fields = ['grn_number', 'vendor_document_id', 'due_date', 'payment_terms', 'payment_reason',
		                   'invoice_line_items']
		# Record any errors in creating invoices
		failed = {}
		# List of the created invoices
		created = []
		# Iterate over the request data and create Invoice and InvoiceLineItem objects
		for data in request_data:
			# Check if all required fields are present
			if not all(field in data for field in required_fields):
				continue
			try:
				# Retrieve the PurchaseOrder object, making sure it belongs to the authenticated vendor
				grn_number = data['grn_number']
				grn = GoodsReceivedNote.objects.get(grn_number=grn_number, purchase_order__vendor=request.user.vendor_profile)
			except ObjectDoesNotExist:
				# Record an error for this entry and continue to the next entry
				failed[grn_number] = f"A GRN with ID {data['grn_number']} was not found for this vendor."
				continue
			# Perform all operations for this invoice atomically
			try:
				with transaction.atomic():
					# Create the Invoice object
					invoice_data = {
						'grn': grn.id,
						'purchase_order': grn.purchase_order.id,
						'external_document_id': data.get('vendor_document_id'),
						'description': data.get('description', ''),
						'due_date': data['due_date'],
						'payment_terms': data['payment_terms'],
						'payment_reason': data['payment_reason']
					}
					invoice_serializer = InvoiceSerializer(data=invoice_data)
					if invoice_serializer.is_valid():
						invoice = invoice_serializer.save()
					else:
						# Record an error for this entry and continue to the next
						failed[grn_number] = ", ".join([str(i) for i in invoice_serializer.errors])
						continue
					# Create InvoiceLineItem objects
					for line_item in data.get('invoice_line_items', []):
						grn_line_item_id = line_item['grn_line_item_id']
						# Retrieve PurchaseOrderLineItem object
						grn_line_item = GoodsReceivedLineItem.objects.get(id=grn_line_item_id,
						                                                 grn=grn.id)
						# Create InvoiceLineItem object
						line_item['invoice'] = invoice.id  # Associate with the created invoice
						line_item['grn_line_item'] = grn_line_item.id  # Associate with the corresponding PO line item
						line_item['po_line_item'] = grn_line_item.purchase_order_line_item.id  # Associate with the corresponding PO line item
						line_item_serializer = InvoiceLineItemSerializer(data=line_item)
						if line_item_serializer.is_valid():
							# Save the created line item
							line_item_serializer.save()
						else:
							# Trigger rollback of this atomic block
							raise ValidationError(line_item_serializer.errors)
					# After creating the line items, seal the created invoice
					invoice.seal_class()
					# Append the created invoice to the list of created invoices
					created.append(InvoiceSerializer(invoice).data)
			except Exception as e:
				# Record an error for this entry and continue to the next
				failed[grn_number] = str(e)
				continue
			
		# If any of the invoices were created, return the created invoices
		if created:
			return APIResponse("Invoices Created", status.HTTP_201_CREATED, data=created)
		
		# If none of the invoices were created, return the errors
		return APIResponse("Failed to create invoices", status.HTTP_400_BAD_REQUEST, data=failed)