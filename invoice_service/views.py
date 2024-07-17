from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from egrn_service.models import PurchaseOrderLineItem, PurchaseOrder, GoodsReceivedNote, GoodsReceivedLineItem
from overrides.rest_framework import APIResponse
from .models import Invoice
from .serializers import InvoiceSerializer, InvoiceLineItemSerializer

class VendorInvoiceView(APIView):
	"""
    Retrieve, update or delete a vendor invoice instance.
    """
	serializer_class = InvoiceSerializer
	permission_classes = (IsAuthenticated,)
	
	def get(self, request):
		# Get all invoices for the authenticated vendor
		invoices = Invoice.objects.filter(purchase_order__vendor=request.user.vendor_profile)
		serializer = InvoiceSerializer(invoices, many=True)
		return APIResponse("Invoices Retrieved", status.HTTP_200_OK, data=serializer.data)
	
	def post(self, request):
		# The request must be a POST request
		data = request.data
		# Required fields
		required_fields = ['grn_number', 'vendor_document_id', 'due_date', 'payment_terms', 'payment_reason',
		                   'invoice_line_items']
		# Check if all required fields are present
		if not all(field in data for field in required_fields):
			return APIResponse(f"Missing required fields: {required_fields}", status=status.HTTP_400_BAD_REQUEST)
		
		try:
			# Retrieve the PurchaseOrder object, making sure it belongs to the authenticated vendor
			grn_number = data['grn_number']
			grn = GoodsReceivedNote.objects.get(grn_number=grn_number, purchase_order__vendor=request.user.vendor_profile)
		except ObjectDoesNotExist:
			return APIResponse(f"A GRN with ID {data['grn_number']} was not found for this vendor.",
			                   status=status.HTTP_404_NOT_FOUND)
		
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
			# print invoice not created
			return APIResponse(invoice_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
		# Create InvoiceLineItem objects
		for line_item in data.get('invoice_line_items', []):
			grn_line_item_id = line_item['grn_line_item_id']
			try:
				# Retrieve PurchaseOrderLineItem object
				grn_line_item = GoodsReceivedLineItem.objects.get(id=grn_line_item_id,
				                                                 grn=grn.id)
			except ObjectDoesNotExist:
				# Rollback the created invoice if line item creation fails
				invoice.delete()
				return APIResponse(
					f"A GRN Line Item with ID {grn_line_item_id} was not found for this GRN.",
					status=status.HTTP_400_BAD_REQUEST)
			
			# Create InvoiceLineItem object
			line_item['invoice'] = invoice.id  # Associate with the created invoice
			line_item['grn_line_item'] = grn_line_item.id  # Associate with the corresponding PO line item
			line_item['po_line_item'] = grn_line_item.purchase_order_line_item.id  # Associate with the corresponding PO line item
			
			try:
				line_item_serializer = InvoiceLineItemSerializer(data=line_item)
				if line_item_serializer.is_valid():
					line_item_serializer.save()
				else:
					# Rollback the created invoice if line item creation fails
					invoice.delete()
					return APIResponse(line_item_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
			except Exception as e:
				# Rollback the created invoice if line item creation fails
				invoice.delete()
				return APIResponse(f"Internal Error: {e}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
		# Seal the created invoice (i.e. generates a unique fingerprint of the invoice)
		invoice.seal_class()
		# Serialize and return the created invoice
		created_invoice = InvoiceSerializer(invoice).data
		return APIResponse(f"Invoice created successfully.", status=status.HTTP_201_CREATED, data=created_invoice)