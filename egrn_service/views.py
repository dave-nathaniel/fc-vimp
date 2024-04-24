# Import necessary modules and classes
import os, sys
import logging
import asyncio
from django.template.loader import render_to_string
from rest_framework import status
from rest_framework.decorators import api_view
from byd_service.rest import RESTServices
from django.contrib.auth import get_user_model
from overrides.rest_framework import APIResponse
from django.core.exceptions import ObjectDoesNotExist
from asgiref.sync import async_to_sync

from .models import GoodsReceivedNote, PurchaseOrder
from .serializers import GoodsReceivedNoteSerializer, PurchaseOrderSerializer
from .tasks import send_email_async

# Initialize REST services
byd_rest_services = RESTServices()
# Get the user model
User = get_user_model()


def delete_items(po):
	del po["Item"]
	return po


def filter_objects(keys_to_keep, objects):
	filtered_objects = []
	# Use dictionary comprehension to filter objects
	for obj in objects:
		filtered_obj = {key: obj[key] for key in keys_to_keep if key in obj}
		filtered_objects.append(filtered_obj)
	
	return filtered_objects


def get_formatted_vendor(id, id_type):
	data = byd_rest_services.get_vendor_by_id(id, id_type=id_type)
	vendor = {
		"InternalID": data["BusinessPartner"]["InternalID"],
		"CategoryCode": data["BusinessPartner"]["CategoryCode"],
		"CategoryCodeText": data["BusinessPartner"]["CategoryCodeText"],
		"BusinessPartnerFormattedName": data["BusinessPartner"]["BusinessPartnerFormattedName"],
	}
	
	return vendor


@api_view(['GET'])
def search_vendor(request, ):
	params = dict(request.GET)
	try:
		query_param = ('email', params['email'][0]) if params['email'] else ('phone', params['phone'][0])
		# Fetch purchase orders for the authenticated user
		vendor = get_formatted_vendor(query_param[1], query_param[1])
		# Data object to hold the return data
		data = {}
		
		if vendor:
			keys_to_keep = ["ObjectID", "UUID", "ID", "CreationDateTime", "LastChangeDateTime", "CurrencyCode",
							"CurrencyCodeText", "TotalGrossAmount", "TotalNetAmount", "TotalTaxAmount",
							"ConsistencyStatusCode",
							"LifeCycleStatusCode", "AcknowledgmentStatusCode", "AcknowledgmentStatusCodeText",
							"DeliveryStatusCode", "DeliveryStatusCodeText", "InvoicingStatusCode",
							"InvoicingStatusCodeText"]
			
			purchase_orders = byd_rest_services.get_vendor_purchase_orders(vendor["InternalID"])
			purchase_orders = filter_objects(keys_to_keep, list(map(delete_items, purchase_orders)))
			
			data["BusinessPartner"] = vendor
			data["PurchaseOrders"] = purchase_orders
			
			return APIResponse("Vendor found.", status.HTTP_200_OK, data=data)
		
		return APIResponse(f"No vendor results found for {query_param[1]} {query_param[1]}.", status.HTTP_404_NOT_FOUND)
	except Exception as e:
		logging.error(e)
		return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_order_items(request, po_id):
	'''
		Retrieve a purchase order with the specified ID from ByD.
		This method is used by the frontend at the point of creating a GoodsReceivedNote to get the items to
		be received.
	'''
	try:
		orders = byd_rest_services.get_purchase_order_by_id(po_id)
		
		if orders:
			# Check if conversions have been defined for any orders in the PO,
			return APIResponse("Purchase Orders Retrieved", status.HTTP_200_OK, data=orders)
		
		return APIResponse(f"Order with ID {po_id} not found.", status.HTTP_404_NOT_FOUND)
	
	except Exception as e:
		logging.error(e)
		return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_order_with_grns(request, po_id):
	try:
		orders = PurchaseOrder.objects.get(po_id=po_id)
		serializer = PurchaseOrderSerializer(orders)
		orders = serializer.data
		
		return APIResponse("Purchase Orders Retrieved", status.HTTP_200_OK, data=orders)
	
	except ObjectDoesNotExist:
		return APIResponse(f"No GRNs created for PO {po_id}", status.HTTP_404_NOT_FOUND)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def create_grn(request, ):
	identifier = "PONumber"  # should be PO_ID
	# keys we NEED to create a GRN
	required_keys = [identifier, "recievedGoods"]
	# the post request
	request_data = request.data
	# Check that all the required keys are present in the request
	required_keys_present = [
		any(
			map(lambda x: r in x, list(request_data.keys()))
		) for r in required_keys
	]
	# If required keys are not present, return an error
	if not all(required_keys_present):
		return APIResponse(f"Missing required key(s) [{', '.join(required_keys)}]", status.HTTP_400_BAD_REQUEST)
	# Check that all the quantityReceived in the recievedGoods object are greater than 0
	for item in request_data["recievedGoods"]:
		if item["quantityReceived"] <= 0:
			return APIResponse(f"Invalid quantity received: {item['quantityReceived']}", status.HTTP_400_BAD_REQUEST)
	# Make the PO_ID key consistent as the identifier
	request_data["po_id"] = request_data[identifier]
	try:
		# Try to create the GRN
		new_grn = GoodsReceivedNote()
		grn_saved = new_grn.save(grn_data=request_data)
		# If the GRN was created successfully, return the created GRN
		if grn_saved:
			created_grn = GoodsReceivedNote.objects.get(id=grn_saved.id)
			# Serialize the GoodsReceivedNote instance along with its related GoodsReceivedLineItem instances
			goods_received_note = GoodsReceivedNoteSerializer(created_grn).data
			# Modify some fields for more straightforward rendering
			goods_received_note['purchase_order']['BuyerParty']['BuyerPartyName'] = goods_received_note['purchase_order']['BuyerParty']['BuyerPartyName'][0]
			goods_received_note['purchase_order']['Supplier']['SupplierName'] = goods_received_note['purchase_order']['Supplier']['SupplierName'][0]
			goods_received_note['purchase_order']['Supplier']['SupplierPostalAddress'] = goods_received_note['purchase_order']['Supplier']['SupplierPostalAddress'][0]
			# Render the HTML content of the template and send the email asynchronously
			html_content = render_to_string('grn_receipt_template.html', {'data': goods_received_note})
			send_email_async(html_content)
			return APIResponse("GRN Created.", status.HTTP_201_CREATED, data=goods_received_note)
		else:
			return APIResponse("Internal Error", status.HTTP_500_INTERNAL_SERVER_ERROR)
	# Return an error if there is an exception
	except Exception as e:
		return APIResponse(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_all_grns(request, ):
	try:
		grns = GoodsReceivedNote.objects.all()
		# Serialize the GoodsReceivedNote instance along with its related GoodsReceivedLineItem instances
		grn_serializer = GoodsReceivedNoteSerializer(grns, many=True)
		goods_received_note = grn_serializer.data
		
		return APIResponse("GRNs Retrieved", status.HTTP_200_OK, data=goods_received_note)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_grn(request, grn_number):
	try:
		grn = GoodsReceivedNote.objects.get(grn_number=grn_number)
		if grn:
			# Serialize the GoodsReceivedNote instance along with its related GoodsReceivedLineItem instances
			grn_serializer = GoodsReceivedNoteSerializer(grn)
			goods_received_note = grn_serializer.data
			return APIResponse("GRN Retrieved", status.HTTP_200_OK, data=goods_received_note)
		else:
			return APIResponse("GRN Not Found", status=status.HTTP_404_NOT_FOUND)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)
