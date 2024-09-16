# Import necessary modules and classes
import os, sys
import logging
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from overrides.authenticate import CombinedAuthentication
from overrides.rest_framework import CustomPagination
from byd_service.rest import RESTServices
from django.contrib.auth import get_user_model
from overrides.rest_framework import APIResponse
from django.core.exceptions import ObjectDoesNotExist

from .models import GoodsReceivedNote, GoodsReceivedLineItem, PurchaseOrder, PurchaseOrderLineItem, ProductConfiguration
from .serializers import GoodsReceivedNoteSerializer, GoodsReceivedLineItemSerializer, PurchaseOrderSerializer


# Initialize REST services
byd_rest_services = RESTServices()
# Get the user model
User = get_user_model()
# Pagination
paginator = CustomPagination()


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
@authentication_classes([AdfsAccessTokenAuthentication,])
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
@authentication_classes([CombinedAuthentication])
def get_purchase_order(request, po_id):
	try:
		try:
			# Fetch purchase orders from the database
			orders = PurchaseOrder.objects.get(po_id=po_id)
		except ObjectDoesNotExist:
			# If the order does not exist in the database, fetch the order from ByD
			byd_orders = byd_rest_services.get_purchase_order_by_id(po_id)
			if byd_orders:
				# If the order exists in ByD, create a new PurchaseOrder object
				po = PurchaseOrder()
				orders = po.create_purchase_order(byd_orders)
			else:
				# If the order does not exist in ByD, return an error
				return APIResponse(f"Order with ID {po_id} not found.", status.HTTP_404_NOT_FOUND)
		# Serialize the PurchaseOrder object
		serializer = PurchaseOrderSerializer(orders)
		return APIResponse("Purchase Orders Retrieved", status.HTTP_200_OK, data=serializer.data)
	except Exception as e:
		# Handle any other errors
		logging.error(f"An error occurred creating a Purchase Order: {e}")
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)

	
@api_view(['POST'])
@authentication_classes([AdfsAccessTokenAuthentication,])
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
	# Make the PO_ID key consistent as the identifier
	request_data["po_id"] = request_data[identifier]
	try:
		# Create the GRN
		created_grn = GoodsReceivedNote().save(grn_data=request_data)
		# Serialize the GoodsReceivedNote instance along with its related GoodsReceivedLineItem instances
		goods_received_note = GoodsReceivedNoteSerializer(created_grn).data
		return APIResponse("GRN Created.", status.HTTP_201_CREATED, data=goods_received_note)
	# Return an error if there is an exception
	except Exception as e:
		return APIResponse(str(e), status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_all_grns(request, ):
	try:
		# Get all GRNs sorted by creation date in descending order
		grns = GoodsReceivedNote.objects.all()#.order_by('-created')
		# Paginate the results
		paginated = paginator.paginate_queryset(grns, request, order_by='-id')
		# Serialize the GoodsReceivedNote instance along with its related GoodsReceivedLineItem instances
		grn_serializer = GoodsReceivedNoteSerializer(paginated, many=True, context={'request':request})
		# Return the paginated response with the serialized GoodsReceivedNote instances
		paginated_data = paginator.get_paginated_response(grn_serializer.data).data
		return APIResponse("GRNs Retrieved", status.HTTP_200_OK, data=paginated_data)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)
	

@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def get_vendors_grns(request, ):
	'''
		Get all GRNs for the authenticated user
	'''
	try:
		po_id = request.query_params.get('po_id')
		grns = GoodsReceivedNote.objects.filter(purchase_order__vendor=request.user.vendor_profile)
		# If the request params contain po_id, filter by po_id
		grns = grns.filter(purchase_order__po_id=po_id) if po_id else grns
		if grns:
			# Paginate the results
			paginated = paginator.paginate_queryset(grns, request, order_by='-id')
			# Serialize the GoodsReceivedNote instance along with its related GoodsReceivedLineItem instances
			grn_serializer = GoodsReceivedNoteSerializer(paginated, many=True, context={'request':request})
			# Return the paginated response with the serialized GoodsReceivedNote instances
			paginated_data = paginator.get_paginated_response(grn_serializer.data).data
			return APIResponse("GRNs Retrieved", status.HTTP_200_OK, data=paginated_data)
		return APIResponse(f"No GRN found.", status=status.HTTP_404_NOT_FOUND)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
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


@api_view(['GET'])
@authentication_classes([CombinedAuthentication,])
def weighted_average(request):
	'''
		Get the weighted average cost for all products or for a specific product, with a history of purchases.
	'''
	def calculate_wac(product_line_items, cumulative_quantity, cumulative_cost):
		# Dictionary to store results grouped by product_id
		product_data = {
			"product_id": product_line_items[0].purchase_order_line_item.product_id,
			"product_name": product_line_items[0].purchase_order_line_item.product_name,
			"starting_quantity": cumulative_quantity,
			"starting_cost": cumulative_cost / cumulative_quantity if cumulative_quantity > 0 else 0,
			"cumulative_quantity": cumulative_quantity,
			"cumulative_cost": cumulative_cost,
			"wac": 0,
			"history": [],
		}

		for line_item in product_line_items:
			purchase_quantity = line_item.purchase_order_line_item.quantity
			purchase_cost = purchase_quantity * line_item.purchase_order_line_item.unit_price
			
			cumulative_quantity = product_data["cumulative_quantity"]
			cumulative_cost = product_data["cumulative_cost"]

			# Update cumulative values with new purchase
			cumulative_quantity += purchase_quantity
			cumulative_cost += purchase_cost

			# Calculate new WAC for the product
			new_wac = cumulative_cost / cumulative_quantity

			# Update product's current data
			product_data.update({
				"cumulative_quantity": cumulative_quantity,
				"cumulative_cost": cumulative_cost,
				"wac": round(new_wac, 2),
			})

			# Add history entry
			product_data["history"].append({
				"date": line_item.date_received,
				"store": line_item.purchase_order_line_item.delivery_store.store_name,
				"purchase_quantity": purchase_quantity,
				"purchase_price_per_unit": purchase_cost / purchase_quantity,
				"purchase_cost": purchase_cost,
				"cumulative_quantity": cumulative_quantity,
				"cumulative_cost": cumulative_cost,
				"wac": round(new_wac, 2),
				"grn": GoodsReceivedLineItemSerializer(line_item).data,
			})

		# Convert defaultdict to a regular dict before returning
		return product_data
	
	products_wac = []
	
	try:
		if request.query_params.get('product_id'):
			products = map(lambda x: x.strip(), request.query_params.get('product_id').split(','))
		else:
			products = GoodsReceivedLineItem.objects.order_by('purchase_order_line_item__product_id').values_list('purchase_order_line_item__product_id', flat=True).distinct()
			
		for product_id in products:
			product_config = ProductConfiguration.objects.filter(product_id=product_id).first()
			cumulative_quantity, cumulative_cost = 0, 0
			if hasattr(product_config, 'metadata') and product_config.metadata:
				cumulative_quantity = product_config.metadata.get('inital_quantity', 0)
				cumulative_cost = product_config.metadata.get('initial_cost', 0) * cumulative_quantity
	
			orders_for_product = GoodsReceivedLineItem.objects.filter(purchase_order_line_item__product_id=product_id).order_by('date_received')
			products_wac.append(calculate_wac(orders_for_product, cumulative_quantity, cumulative_cost)) if orders_for_product else None
			
		# # Paginate the results
		paginated = paginator.paginate_queryset(products_wac, request)
		paginated_data = paginator.get_paginated_response(paginated).data
		return APIResponse("Weighted Averages Calculated", status.HTTP_200_OK, data=paginated_data)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)