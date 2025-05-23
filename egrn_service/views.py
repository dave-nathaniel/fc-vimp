# Import necessary modules and classes
import os, sys
import logging
from datetime import datetime
from django.forms import model_to_dict
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from overrides.authenticate import CombinedAuthentication
from overrides.rest_framework import CustomPagination
from byd_service.rest import RESTServices
from django.contrib.auth import get_user_model
from overrides.rest_framework import APIResponse
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q

from .models import GoodsReceivedNote, GoodsReceivedLineItem, PurchaseOrder, PurchaseOrderLineItem, ProductConfiguration, Store
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
		user_stores = Store.objects.filter(store_email=request.user.email)
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
		serializer = PurchaseOrderSerializer(orders).data
		serializer["Item"] = list(
			filter(lambda x: x.get('delivery_store').get('id') in [s.id for s in user_stores], serializer["Item"])
		)
		if len(serializer["Item"]) > 0:
			serializer["stores"] = filter(
				lambda x: x.id in [s for s in map(lambda x: x["delivery_store"], serializer["Item"])],
				user_stores
			)
			return APIResponse("Purchase Orders Retrieved", status.HTTP_200_OK, data=serializer)
		else:
			return APIResponse(f"No orders found in {po_id} for your stores: {', '.join([s.store_name for s in user_stores])}.", status.HTTP_404_NOT_FOUND)
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
		# Filter for only the PO Line items that the user has permission to receive
		permitted_to_receive_items = (PurchaseOrderLineItem.objects.filter(object_id__in=map(lambda x: x['itemObjectID'], request_data["recievedGoods"]))
							.filter(delivery_store__store_email=request.user.email))
		# If there are no items that the user has permission to receive, return an error
		if not permitted_to_receive_items:
			return APIResponse("User does not have permission to receive these items.", status.HTTP_403_FORBIDDEN)
		# Filter the request data to only include the items that the user has permission to receive
		request_data["recievedGoods"] = list(filter(lambda x: x['itemObjectID'] in [i.object_id for i in permitted_to_receive_items], request_data["recievedGoods"]))
		
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
		user_stores = Store.objects.filter(store_email=request.user.email)
		# Get all GRNs sorted by creation date in descending order
		grns = GoodsReceivedNote.objects.filter(
			line_items__purchase_order_line_item__delivery_store__in=user_stores
		)
		if grns:
			# Paginate the results
			paginated = paginator.paginate_queryset(grns, request, order_by='-id')
			# Serialize the GoodsReceivedNote instance along with its related GoodsReceivedLineItem instances
			grn_serializer = GoodsReceivedNoteSerializer(paginated, many=True, context={'request':request})
			# Return the paginated response with the serialized GoodsReceivedNote instances
			paginated_data = paginator.get_paginated_response(grn_serializer.data).data
			return APIResponse("GRNs Retrieved", status.HTTP_200_OK, data=paginated_data)
		return APIResponse(f"No GRNs found for your stores: {', '.join([s.store_name for s in user_stores])}", status.HTTP_404_NOT_FOUND)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
def filter_grns(request, ):
	'''
		Get GRNs based on the given filters, if any.
		The filters are:
			- 'po_id': Filter GRNs by purchase order ID
			- 'date_created': Filter GRNs by creation date
			- 'delivery_stores': Filter GRNs by delivery store ID
			- 'delivery_status_code': Filter GRNs by delivery status code
			- 'invoice_status_code': Filter GRNs by invoice status code
			- 'start_date': Filter GRNs by start date
			- 'end_date': Filter GRNs by end date
			- 'vendor_internal_id': Filter GRNs by vendor internal ID (from ByD)
	'''
	# These are filters that we can use directly on the queryset
	django_filters = {}
	# These are filters that we need to manually apply on the queryset after fetching the base queryset
	custom_filters = {
		'delivery_status_code': None,
		'invoice_status_code': None,
	}
	
	for key in request.query_params:
		# Remove unnecessary filter keys
		if key in custom_filters.keys():
			custom_filters[key] = request.query_params.get(key)
		# Convert the filter to the appropriate data type or the appropriate field name
		if key == 'date_created':
			django_filters['created'] = request.query_params.get(key)
		if key == 'start_date':
			django_filters['created__gte'] = request.query_params.get(key)
		if key == 'end_date':
			django_filters['created__lte'] = request.query_params.get(key)
		if key in ['po_id']:
			django_filters[f'purchase_order__{key}'] = request.query_params.get(key)
		if key == 'vendor_internal_id':
			django_filters['purchase_order__vendor__byd_internal_id'] = request.query_params.get(key)
		if key == 'delivery_stores':
			filter_stores = request.query_params.get(key)
			# Split the store names and build a Q object for icontains lookup
			store_names = [name.strip() for name in filter_stores.split(',') if name.strip()]
			if store_names:
				store_query = Q()
				for name in store_names:
					store_query |= Q(line_items__purchase_order_line_item__delivery_store__store_name__icontains=name)
				# Save the Q object for later use
				django_filters['__custom_store_name_q'] = store_query

	try:
		# Extract and remove the custom Q object if present
		store_name_q = django_filters.pop('__custom_store_name_q', None)
		# Apply filters to get the base queryset
		grns = GoodsReceivedNote.objects.filter(**django_filters)
		if store_name_q:
			grns = grns.filter(store_name_q)
		grns = grns.order_by('-id')
		if grns.exists():
			# Paginate the results
			paginated = paginator.paginate_queryset(grns, request)
			# Serialize the paginated queryset
			serialized_data = GoodsReceivedNoteSerializer(paginated, many=True, context={'request': request}).data
			# Apply custom filtering after serialization (since 'delivery_status_code' comes from the serializer)
			if custom_filters:
				# Use only custom filters that are not None
				custom_filters = {k: v for k, v in custom_filters.items() if v is not None}
				if 'delivery_status_code' in custom_filters:
					# Filter based on serialized data
					serialized_data = [grn for grn in serialized_data if grn.get('purchase_order', {}).get('delivery_status_code') == custom_filters.get('delivery_status_code')]
				if 'invoice_status_code' in custom_filters:
					# Filter based on serialized data
					serialized_data = [grn for grn in serialized_data if grn.get('invoice_status_code') == custom_filters.get('invoice_status_code')]
			
			# Return the filtered, paginated response
			return paginator.get_paginated_response(serialized_data)
		return APIResponse("No GRNs found for the specified criteria.", status=status.HTTP_404_NOT_FOUND)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
	

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
			purchase_quantity = line_item.quantity_received
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
			
			# Get all orders for the current product and order by date received
			orders_for_product = GoodsReceivedLineItem.objects.filter(purchase_order_line_item__product_id=product_id).order_by('date_received')
			# If a date was supplied in the request, filter for only orders on or before that date
			if request.query_params.get('date'):
				orders_for_product = orders_for_product.filter(
					date_received__lte=datetime.strptime(
						request.query_params.get('date'),
						'%Y-%m-%d'
					)
				)
				# If no orders were found for the given date, continue to the next product
				if not orders_for_product:
					continue
			
			# Calculate and add the WAC for the current product to the results list
			products_wac.append(
				calculate_wac(orders_for_product, cumulative_quantity, cumulative_cost)
			) if orders_for_product else None
			
		# # Paginate the results
		paginated = paginator.paginate_queryset(products_wac, request)
		paginated_data = paginator.get_paginated_response(paginated).data
		return APIResponse("Weighted Averages Calculated", status.HTTP_200_OK, data=paginated_data)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)