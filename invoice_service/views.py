from django.core.exceptions import ObjectDoesNotExist, ValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from egrn_service.models import GoodsReceivedNote, GoodsReceivedLineItem
from overrides.rest_framework import APIResponse
from overrides.rest_framework import CustomPagination
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
		# Get all invoices for the authenticated vendor
		invoices = Invoice.objects.filter(purchase_order__vendor=request.user.vendor_profile)
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
				failed['grn_number'] = f"A GRN with ID {data['grn_number']} was not found for this vendor."
				continue
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
				# Record an error for this entry and continue to the next entry
				failed[grn_number] = ", ".join([i for i in invoice_serializer.errors])
				continue
			# Create InvoiceLineItem objects
			for line_item in data.get('invoice_line_items', []):
				
				try:
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
						# Rollback the created invoice and record and error for this entry if line item creation fails
						raise ValidationError(line_item_serializer.errors)
				except ObjectDoesNotExist:
					# Rollback the created invoice and record an error for this entry if line item creation fails
					invoice.delete()
					failed[grn_number] = f"A GRN Line Item with ID {grn_line_item_id} was not found for this GRN."
					continue
				except ValidationError as e:
					invoice.delete()
					e = ', '.join([i for i in e])
					failed[grn_number] = e
					continue
				except Exception as e:
					invoice.delete()
					failed[grn_number] = e
					continue
					
			# After creating the line items, seal the created invoice (i.e. generates a unique fingerprint of the invoice and it's associated line items)
			invoice.seal_class()
			# Append the created invoice to the list of created invoices
			created.append(InvoiceSerializer(invoice).data)
		
		# If any of the invoices were created, return the created invoices
		if created:
			return APIResponse("Invoices Created", status.HTTP_201_CREATED, data=created)
		
		# If none of the invoices were created, return the errors
		return APIResponse("Failed to create invoices", status.HTTP_400_BAD_REQUEST, data=failed)
		