# Import necessary modules and classes
import os, sys
import logging
from rest_framework import status
from rest_framework.decorators import api_view
from django.db import IntegrityError
from byd_service.rest import RESTServices
from django.contrib.auth import get_user_model
from overrides.rest_framework import APIResponse
# from rest_framework.permissions import IsAuthenticated
# from rest_framework_simplejwt.views import TokenObtainPairView

# Initialize REST services
byd_rest_services = RESTServices()
# Get the user model
User = get_user_model()


def filter_objects(keys_to_keep, objects):
	filtered_objects = []

	# Use dictionary comprehension to filter objects
	for obj in objects:
		# print(obj)
		# sys.exit()
		filtered_obj = {key: obj[key] for key in keys_to_keep if key in obj}
		filtered_objects.append(filtered_obj)

	return filtered_objects
	

@api_view(['GET'])
def search_vendor(request, ):
	params = dict(request.GET)
	try:
		query_param = ('email', params['email'][0]) if params['email'] else ('phone', params['phone'][0])
		
		# Fetch purchase orders for the authenticated user
		data = byd_rest_services.get_vendor_by_id(query_param[1], id_type=query_param[0])
		
		if data:
			vendor = {
				"BusinessPartner": {
					"InternalID": data["BusinessPartner"]["InternalID"],
					"CategoryCode": data["BusinessPartner"]["CategoryCode"],
					"CategoryCodeText": data["BusinessPartner"]["CategoryCodeText"],
					"BusinessPartnerFormattedName": data["BusinessPartner"]["BusinessPartnerFormattedName"],
				}
			}
			return APIResponse("Vendor found.", status.HTTP_200_OK, data=vendor)

	except Exception as e:
		logging.error(e)
		return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)

	return APIResponse("Error.", status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def get_vendors_orders(request, vendor_id):
	internal_id = vendor_id
	keys_to_keep = ["ObjectID", "UUID", "ID", "CreationDateTime", "LastChangeDateTime", "CurrencyCode", "CurrencyCodeText", "TotalGrossAmount", "TotalNetAmount", "TotalTaxAmount", "ConsistencyStatusCode", "LifeCycleStatusCode", "AcknowledgmentStatusCode", "AcknowledgmentStatusCodeText", "DeliveryStatusCode", "DeliveryStatusCodeText", "InvoicingStatusCode", "InvoicingStatusCodeText"]
	
	try:
		def delete_items(po):
			del po["Item"]
			return po

		orders = byd_rest_services.get_vendor_purchase_orders(internal_id)

		if orders:
			response = filter_objects(keys_to_keep, list(map(delete_items, orders)))
			return APIResponse("Purchase Orders Retrieved", status.HTTP_200_OK, data=response)

	except Exception as e:
		logging.error(e)
		return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)

	return APIResponse("Error.", status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def get_order_items(request, vendor_id, po_id):
	# Fetch purchase orders for the authenticated user
	internal_id = vendor_id

	keys_to_keep = ["ObjectID", "UUID", "ID", "CreationDateTime", "LastChangeDateTime", "CurrencyCode", "CurrencyCodeText", "TotalGrossAmount", "TotalNetAmount", "TotalTaxAmount", "ConsistencyStatusCode", "LifeCycleStatusCode", "AcknowledgmentStatusCode", "AcknowledgmentStatusCodeText", "DeliveryStatusCode", "DeliveryStatusCodeText", "InvoicingStatusCode", "InvoicingStatusCodeText", "Item"]
	try:
		orders = byd_rest_services.get_vendor_purchase_orders(internal_id)
		
		if orders:
			for order in orders:
				if order["ID"] == po_id:
					response = order
					return APIResponse("Purchase Orders Retrieved", status.HTTP_200_OK, data=response)

			return APIResponse(f"Order with ID {object_id} not found for vendor {internal_id}", status.HTTP_404_NOT_FOUND)

	except Exception as e:
		logging.error(e)
		return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)

	return APIResponse("Error.", status.HTTP_400_BAD_REQUEST)