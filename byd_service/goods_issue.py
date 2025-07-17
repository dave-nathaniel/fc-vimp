import datetime
import os
import logging
import json
from time import sleep
from .soap import SOAPServices
from .util import ordinal
from pathlib import Path

# Constants
MAX_RETRY_POSTING = 3
soap_endpoint = 'https://my350679.sapbydesign.com/sap/bc/srt/scs/sap/inventoryprocessinggoodsandac3'
wsdl_path = os.path.join(Path(__file__).resolve().parent, 'wsdl', 'InventoryProcessingGoodsAndActivityConfirmationGoodsMovementIn.wsdl')

# Initialize the SOAP client and authenticate with SAP
try:
	ss = SOAPServices()
	ss.wsdl_path = wsdl_path
	ss.connect()
	# Access the services (operations) provided by the SOAP endpoint
	soap_client = ss.client.create_service("{http://sap.com/xi/AP/LogisticsExecution/Global}binding", soap_endpoint)
except Exception as e:
	raise e


def format_inventory_item(external_item_id, material_internal_id, owner_party_internal_id, 
						 inventory_restricted_use_indicator, logistics_area_id, 
						 quantity=None, unit_code=None, inventory_stock_status_code=None, 
						 identified_stock_id=None, accounting_coding_block=None):
	"""
	Format a dictionary for an inventory change item to match XML structure exactly.
	
	Args:
		external_item_id (str): External identifier for the item
		material_internal_id (str): Internal material identifier
		owner_party_internal_id (str): Internal owner party identifier
		inventory_restricted_use_indicator (bool): Whether inventory has restricted use
		logistics_area_id (str): Logistics area identifier
		quantity (float, optional): Quantity for the change
		unit_code (str, optional): Unit of measure code
		inventory_stock_status_code (str, optional): Stock status code
		identified_stock_id (str, optional): Identified stock identifier
		accounting_coding_block (dict, optional): Accounting coding block information
	
	Returns:
		dict: Formatted inventory change item dictionary matching XML structure
	"""
	item = {
		"ExternalItemID": external_item_id,
		"MaterialInternalID": material_internal_id,
		"OwnerPartyInternalID": owner_party_internal_id,
		"InventoryRestrictedUseIndicator": 'true' if inventory_restricted_use_indicator else 'false',
		"InventoryStockStatusCode": inventory_stock_status_code or "",
		"IdentifiedStockID": identified_stock_id or "",
		"LogisticsAreaID": logistics_area_id
	}
	
	# Add quantity structure to match XML exactly
	if quantity and unit_code:
		# Set the type for the quantity in the request
		quantity_type = ss.client.get_type('{http://sap.com/xi/AP/Common/GDT}Quantity')
		item["InventoryItemChangeQuantity"] = {
			"Quantity": quantity_type(quantity, unitCode=unit_code),
			"QuantityTypeCode": unit_code
		}
	
	if accounting_coding_block:
		item["AccountingCodingBlock"] = accounting_coding_block
	
	return item


def post_goods_consumption_for_cost_center(external_id, site_id, inventory_movement_direction_code, 
										  inventory_items, transaction_datetime=None, cost_center_id=None):
	"""
	Post goods consumption for cost center to SAP Business ByDesign (ByD) system.
	Supports both single inventory item and multiple inventory items.
	
	Args:
		external_id (str): External identifier for the goods and activity confirmation
		site_id (str): Site identifier
		inventory_movement_direction_code (str): Direction code for inventory movement
		inventory_items (dict or list): Single inventory change item or list of inventory change items to be posted
		transaction_datetime (str, optional): Transaction date and time in ISO format
		cost_center_id (str, optional): Cost center identifier
	
	Returns:
		bool: True if the posting was successful, False otherwise.
	"""
	def send_request(request):
		try:
			response = soap_client.DoGoodsConsumptionForCostCenter(
				request
			)
			if response['Log'] is not None:
				logging.error(f"The following issues were raised by SAP ByD: ")
				logging.error(f"{chr(10)}{chr(10).join(['Issue ' + str(counter + 1) + ': ' + item['Note'] + '.' for counter, item in enumerate(response['Log']['Item'])])}")
			else:
				return True
		except Exception as e:
			logging.error(f"The following exception occurred while posting goods consumption to SAP ByD: {e}")

		return False
	
	# Build the goods and activity confirmation object to match XML structure exactly
	goods_confirmation = {
		"ExternalID": external_id,
		"SiteID": site_id,
		"InventoryMovementDirectionCode": inventory_movement_direction_code,
		"InventoryChangeItemGoodsConsumptionInformationForCostCenter": inventory_items
	}
	
	# Add optional fields if provided
	if cost_center_id:
		goods_confirmation["CostCenterID"] = cost_center_id
	
	if transaction_datetime:
		goods_confirmation["TransactionDateTime"] = transaction_datetime
	
	# Build the main request object to match XML structure
	request = {
		"GoodsAndActivityConfirmation": goods_confirmation
	}

	logging.info(f"Posting goods consumption for {len(inventory_items)} item(s)")

	posted = send_request(goods_confirmation)
	retry_counter = 1

	while retry_counter < MAX_RETRY_POSTING and not posted:
		retry_counter += 1
		logging.info(f"Attempting to post goods consumption for the {ordinal(retry_counter)} time.")
		sleep(2)
		posted = send_request(request)
		
	logging.error("Goods consumption posting may have failed.") if not posted else logging.info("Goods consumption posted successfully. \n")

	return posted


def example_usage():
	"""
	Example usage demonstrating both single and multiple inventory items.
	"""
	# Create inventory items
	inventory_items = [
		{
			"external_item_id": "E20250-1",
			"material_internal_id": "RM1000072",
			"owner_party_internal_id": "FC-0001",
			"inventory_restricted_use_indicator": False,
			"logistics_area_id": "4100003-17",
			"quantity": 1.0,
			"unit_code": "KGM"
		}
	]
	
	# Example 1: Single item posting
	print("=== Example 1: Single Item Posting ===")
	success_single = post_goods_consumption_for_cost_center(
		external_id="E20250",
		site_id="4100003-17",
		inventory_movement_direction_code="1",
		inventory_items=[
			format_inventory_item(**item) for item in inventory_items
		],
		transaction_datetime="2025-07-17T09:30:00.0000000Z",
		cost_center_id="4100003-17"
	)
	
	print(f"Single item posting {'successful' if success_single else 'failed'}")
	
	return success_single