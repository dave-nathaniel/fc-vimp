# Import necessary modules and classes
import os, sys
import logging
from rest_framework import status
from rest_framework.decorators import api_view
from django.db import IntegrityError
from byd_service.rest import RESTServices
from django.contrib.auth import get_user_model
from overrides.rest_framework import APIResponse

from .models import GoodsReceivedNote
from .serializers import GoodsReceivedNoteSerializer, GoodsReceivedLineItemSerializer


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
        data = byd_rest_services.get_vendor_by_id(query_param[1], id_type=query_param[1])
        
        if data:
            def delete_items(po):
                del po["Item"]
                return po
            
            keys_to_keep = ["ObjectID", "UUID", "ID", "CreationDateTime", "LastChangeDateTime", "CurrencyCode",
                            "CurrencyCodeText", "TotalGrossAmount", "TotalNetAmount", "TotalTaxAmount",
                            "ConsistencyStatusCode",
                            "LifeCycleStatusCode", "AcknowledgmentStatusCode", "AcknowledgmentStatusCodeText",
                            "DeliveryStatusCode", "DeliveryStatusCodeText", "InvoicingStatusCode",
                            "InvoicingStatusCodeText"]
            
            purchase_orders = byd_rest_services.get_vendor_purchase_orders(data["BusinessPartner"]["InternalID"])
            purchase_orders = filter_objects(keys_to_keep, list(map(delete_items, purchase_orders)))
            
            vendor = {
                "BusinessPartner": {
                    "InternalID": data["BusinessPartner"]["InternalID"],
                    "CategoryCode": data["BusinessPartner"]["CategoryCode"],
                    "CategoryCodeText": data["BusinessPartner"]["CategoryCodeText"],
                    "BusinessPartnerFormattedName": data["BusinessPartner"]["BusinessPartnerFormattedName"],
                },
                "PurchaseOrders": purchase_orders
            }
            return APIResponse("Vendor found.", status.HTTP_200_OK, data=vendor)
        
        return APIResponse(f"No vendor results found for {query_param[1]} {query_param[1]}.", status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logging.error(e)
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_order_items(request, po_id):
    # Fetch purchase orders for the authenticated user
    
    keys_to_keep = ["ObjectID", "UUID", "ID", "CreationDateTime", "LastChangeDateTime", "CurrencyCode",
                    "CurrencyCodeText", "TotalGrossAmount", "TotalNetAmount", "TotalTaxAmount", "ConsistencyStatusCode",
                    "LifeCycleStatusCode", "AcknowledgmentStatusCode", "AcknowledgmentStatusCodeText",
                    "DeliveryStatusCode", "DeliveryStatusCodeText", "InvoicingStatusCode", "InvoicingStatusCodeText",
                    "Item"]
    try:
        orders = byd_rest_services.get_purchase_order_by_id(po_id)
        
        if orders:
            return APIResponse("Purchase Orders Retrieved", status.HTTP_200_OK, data=orders)
        
        return APIResponse(f"Order with ID {po_id} not found.",
                           status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        logging.error(e)
        return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return APIResponse("Error.", status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def create_grn(request,):
    identifier = "PONumber" #should be PO_ID
    # keys we NEED to create a GRN
    required_keys = [identifier, "GRN", "recievedGoods"]
    # the post request
    request_data = request.data
    # Check that all the required keys are present in the request
    required_keys_present = [
        any(
            map(lambda x: r in x, list(request_data.keys()))
        ) for r in required_keys
    ]
    
    if not all(required_keys_present):
        return APIResponse(f"Missing required key(s) [{', '.join(required_keys)}]", status.HTTP_400_BAD_REQUEST)
    
    request_data["po_id"] = request_data[identifier]
    
    new_grn = GoodsReceivedNote()
    grn_saved = new_grn.save(grn_data=request_data)
    
    if grn_saved:
        created_grn = GoodsReceivedNote.objects.get(id=grn_saved.id)
        
        # Serialize the GoodsReceivedNote instance along with its related GoodsReceivedLineItem instances
        grn_serializer = GoodsReceivedNoteSerializer(created_grn)
        related_line_items = created_grn.goodsreceivedlineitem_set.all()
        line_items_serializer = GoodsReceivedLineItemSerializer(related_line_items, many=True)
        
        goods_received_note = grn_serializer.data
        goods_received_note["line_items"] = line_items_serializer.data
        
        # print(po_data)
        return APIResponse("GRN Created", status.HTTP_201_CREATED, data=goods_received_note)