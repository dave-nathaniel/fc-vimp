import os
import json
import logging
import time
from requests import get, post
from pathlib import Path
from dotenv import load_dotenv
from django.utils import timezone

from .authenticate import SAPAuthentication

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

logger = logging.getLogger(__name__)

# Initialize the authentication class
sap_auth = SAPAuthentication()

@sap_auth.http_authentication
class RESTServices:
	'''
		RESTful API for interacting with SAP's ByD system
	'''
	
	endpoint = os.getenv('SAP_URL')
	# Initialize a CSRF token to None initially
	session = None
	# Initialize headers that are required for authentication
	auth_headers = {}
	# Initialize the SAP token to None initially
	auth = None
	
	def __init__(self):
		self.last_token_refresh = 0
		self.token_refresh_interval = 300  # 5 minutes
	
	def refresh_csrf_token(self):
		"""Refresh the CSRF token if it's been more than 5 minutes since the last refresh"""
		current_time = time.time()
		if current_time - self.last_token_refresh > self.token_refresh_interval:
			try:
				action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khpurchaseorder/"
				headers = {"x-csrf-token": "fetch"}
				response = self.session.get(action_url, auth=self.auth, headers=headers, timeout=30)
				if response.status_code == 200:
					self.auth_headers['x-csrf-token'] = response.headers.get('x-csrf-token', '')
					self.last_token_refresh = current_time
					logger.info("CSRF token refreshed successfully")
				else:
					logger.error(f"Failed to refresh CSRF token. Status code: {response.status_code}")
					raise Exception(f"Failed to refresh CSRF token. Status code: {response.status_code}")
			except Exception as e:
				logger.error(f"Error refreshing CSRF token: {str(e)}")
				raise
	
	def check_object_lock(self, object_id: str, object_type: str) -> bool:
		"""Check if an object is locked in SAP ByD"""
		try:
			if object_type == 'delivery':
				check_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khinbounddelivery/InboundDeliveryCollection('{object_id}')"
			elif object_type == 'invoice':
				check_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khsupplierinvoice/SupplierInvoiceCollection('{object_id}')"
			else:
				raise ValueError(f"Unsupported object type: {object_type}")
			
			response = self.session.get(check_url, auth=self.auth, timeout=30)
			return response.status_code == 423  # 423 means object is locked
		except Exception as e:
			logger.error(f"Error checking object lock: {str(e)}")
			return False
	
	def __get__(self, *args, **kwargs):
		self.refresh_csrf_token()
		return self.session.get(*args, **kwargs, auth=self.auth)
	
	def __post__(self, *args, **kwargs):
		'''
			This method makes a POST request to the given URL with CSRF protection
		'''
		self.refresh_csrf_token()
		headers = {
			'Accept': 'application/json',
			'Content-Type': 'application/json'
		}
		headers.update(self.auth_headers)
		return self.session.post(*args, **kwargs, headers=headers, auth=self.auth)

	def get_vendor_by_id(self, vendor_id, id_type='email'):
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khbusinesspartner/CurrentDefaultAddressInformationCollection?$format=json&$expand=EMail,BusinessPartner,ConventionalPhone,MobilePhone&$select=EMail,BusinessPartner,ConventionalPhone,MobilePhone&$top=10"
		query_url = f"{action_url}&$filter=EMail/URI eq '{vendor_id}'"

		if id_type == 'phone':
			vendor_id = vendor_id.strip()[-10:]
			query_url = f"{action_url}&$filter=substringof('{vendor_id}',ConventionalPhone/NormalisedNumberDescription)"

		# Make a request with HTTP Basic Authentication
		response = self.__get__(query_url)

		if response.status_code == 200:
			try:
				response_json = json.loads(response.text)
			except Exception as e:
				raise e

			results = response_json["d"]["results"]

			if results:
				active = list(
					filter(lambda x: int(x['BusinessPartner']['LifeCycleStatusCode'])==2, results)
				)
				return active[0] if active else False

		return False

	def get_vendor_purchase_orders(self, internal_id):
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khpurchaseorder/PurchaseOrderCollection?$format=json&$expand=Supplier,Item&$filter=Supplier/PartyID eq '{internal_id}'"

		# Make a request with HTTP Basic Authentication
		response = self.__get__(action_url)

		if response.status_code == 200:
			try:
				response_json = json.loads(response.text)
				results = response_json["d"]["results"]

				# Keys to unset
				keys_to_unset = ['AttachmentFolder', 'Notes', 'PaymentTerms', 'BuyerParty', 'BillToParty',
								 'EmployeeResponsible', 'PurchasingUnit', 'Supplier', '__metadata']
				for result in results:
					# Unset keys from the dictionary
					for key in keys_to_unset:
						if key in result:
							del result[key]
				return results
			except Exception as e:
				raise e

		return False

	def get_purchase_order_by_id(self, PurchaseOrderID):
		action_url: str = (f"{self.endpoint}/sap/byd/odata/cust/v1/khpurchaseorder/PurchaseOrderCollection?$format=json"
						   f"&$expand=Supplier/SupplierName,Supplier/SupplierFormattedAddress,"
						   f"BuyerParty,BuyerParty/BuyerPartyName,"
						   f"Supplier/SupplierPostalAddress,"
						   f"ApproverParty/ApproverPartyName,"
						   f"Item/ItemShipToLocation/DeliveryAddress/DeliveryPostalAddress&$filter=ID eq '"
						   f"{PurchaseOrderID}'")

		# Make a request with HTTP Basic Authentication
		response = self.__get__(action_url)

		if response.status_code == 200:
			try:
				response_json = json.loads(response.text)
				results = response_json["d"]["results"]
				return results[0] if results else False
			except Exception as e:
				raise e

		return False
	
	# GRN Creation
	def create_grn(self, grn_data: dict) -> dict:
		'''
			Create a Goods and Service Acknowledgement (GRN) in SAP ByD
		'''
		
		# Action URL for creating a Goods and Service Acknowledgement (GRN) in SAP ByD
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khgoodsandserviceacknowledgement/GoodsAndServiceAcknowledgementCollection"
		
		try:
			# Make a request with HTTP Basic Authentication
			response = self.__post__(action_url, json=grn_data)
			if response.status_code == 201:
				logging.info(f"GRN successfully created in SAP ByD.")
				return response.json()
			else:
				logging.error(f"Failed to create GRN: {response.text}")
				raise Exception(f"Error from SAP: {response.text}")
		except Exception as e:
			raise Exception(f"Error creating GRN: {e}")
	
	def post_grn(self, object_id: str) -> dict:
		'''
			Post a Goods and Service Acknowledgement (GRN) in SAP ByD
		'''
		# Action URL for creating a Goods and Service Acknowledgement (GRN) in SAP ByD
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khgoodsandserviceacknowledgement/SubmitForRelease?ObjectID='{object_id}'"
		try:
			# Make a request with HTTP Basic Authentication
			response = self.__post__(action_url)
			if response.status_code == 200:
				logging.info(f"GRN successfully POSTED.")
				return response.json()
			else:
				logging.error(f"Failed to create GRN: {response.text}")
				raise Exception(f"Error from SAP: {response.text}")
		except Exception as e:
			raise Exception(f"Error creating GRN: {e}")
	
	# Supplier Invoice Creation
	def create_supplier_invoice(self, invoice_data: dict) -> dict:
		'''
			Create a Supplier Invoice in SAP ByD
		'''
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khsupplierinvoice/SupplierInvoiceCollection"
		calculate_gross = f"{self.endpoint}/sap/byd/odata/cust/v1/khsupplierinvoice/CalculateGrossAmount?ObjectID="
		calculate_tax = f"{self.endpoint}/sap/byd/odata/cust/v1/khsupplierinvoice/CalculateTaxAmount?ObjectID="
		try:
			self.refresh_csrf_token()
			response = self.__post__(action_url, json=invoice_data)
			if response.status_code == 201:
				response_data = response.json()
				logger.info(f"Invoice successfully created in SAP ByD.")
				object_id = response_data.get("d", {}).get("results", {}).get("ObjectID")
				
				# Add a small delay before calculations
				time.sleep(2)
				
				# Calculate gross amount
				gross_url = f"{calculate_gross}'{object_id}'"
				gross_response = self.__post__(gross_url)
				if gross_response.status_code == 200:
					# Add a small delay before tax calculation
					time.sleep(2)
					# Calculate tax amount
					tax_url = f"{calculate_tax}'{object_id}'"
					tax_response = self.__post__(tax_url)
					if tax_response.status_code != 200:
						logger.error(f"Failed to calculate tax amount: {tax_response.text}")
						raise Exception(f"Error from SAP: {tax_response.text}")
				else:
					logger.error(f"Failed to calculate gross amount: {gross_response.text}")
					raise Exception(f"Error from SAP: {gross_response.text}")
					
				return response.json()
			else:
				logger.error(f"Failed to create Invoice: {response.text}")
				raise Exception(f"{response.text}")
		except Exception as e:
			logger.error(f"Error creating Invoice: {str(e)}")
			raise
			
	def post_invoice(self, object_id: str) -> dict:
		'''
			Post a Supplier Invoice in SAP ByD
		'''
		# Check if object is locked
		if self.check_object_lock(object_id, 'invoice'):
			logger.warning(f"Invoice {object_id} is locked. Will retry later.")
			raise Exception("Object is locked")
			
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khsupplierinvoice/FinishDataEntryProcessing?ObjectID='{object_id}'"
		try:
			self.refresh_csrf_token()
			response = self.__post__(action_url)
			if response.status_code == 200:
				logger.info(f"Invoice successfully POSTED.")
				return response.json()
			else:
				logger.error(f"Failed to post Invoice: {response.text}")
				raise Exception(f"Error from SAP: {response.text}")
		except Exception as e:
			logger.error(f"Error posting Invoice: {str(e)}")
			raise
	
	def create_inbound_delivery_notification(self, delivery_data: dict) -> dict:
		'''
			Create an Inbound Delivery Notification in SAP ByD
		'''
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khinbounddelivery/InboundDeliveryCollection"
		try:
			self.refresh_csrf_token()
			response = self.__post__(action_url, json=delivery_data)
			if response.status_code == 201:
				logger.info(f"Delivery Notification successfully created in SAP ByD.")
				return response.json()
			else:
				logger.error(f"Failed to create Delivery Notification: {response.text}")
				raise Exception(f"Error from SAP: {response.text}")
		except Exception as e:
			logger.error(f"Error creating Delivery Notification: {str(e)}")
			raise
	
	def post_delivery_notification(self, object_id: str) -> dict:
		'''
			Post an Inbound Delivery Notification in SAP ByD
		'''
		# Check if object is locked
		if self.check_object_lock(object_id, 'delivery'):
			logger.warning(f"Delivery Notification {object_id} is locked. Will retry later.")
			raise Exception("Object is locked")
			
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khinbounddelivery/PostGoodsReceipt?ObjectID='{object_id}'"
		try:
			self.refresh_csrf_token()
			response = self.__post__(action_url)
			if response.status_code == 200:
				logger.info(f"Delivery Notification successfully POSTED.")
				return response.json()
			else:
				logger.error(f"Failed to post Delivery Notification: {response.text}")
				raise Exception(f"Error from SAP: {response.text}")
		except Exception as e:
			logger.error(f"Error posting Delivery Notification: {str(e)}")
			raise
	
	# Sales Order methods for store-to-store transfers
	def get_sales_order_by_id(self, sales_order_id: str) -> dict:
		'''
			Fetch a sales order from SAP ByD by ID
		'''
		action_url = (f"{self.endpoint}/sap/byd/odata/cust/v1/khsalesorder/SalesOrderCollection?$format=json"
					  f"&$expand=Item,BuyerParty,SellerParty&$filter=ID eq '{sales_order_id}'")
		
		try:
			response = self.__get__(action_url)
			if response.status_code == 200:
				response_json = json.loads(response.text)
				results = response_json["d"]["results"]
				return results[0] if results else None
			else:
				logger.error(f"Failed to fetch sales order {sales_order_id}: {response.text}")
				return None
		except Exception as e:
			logger.error(f"Error fetching sales order {sales_order_id}: {str(e)}")
			raise
	
	def get_store_sales_orders(self, store_id: str) -> list:
		'''
			Get sales orders for a specific store (as source or destination)
		'''
		# This assumes store_id maps to a cost center or similar identifier in SAP ByD
		action_url = (f"{self.endpoint}/sap/byd/odata/cust/v1/khsalesorder/SalesOrderCollection?$format=json"
					  f"&$expand=Item,BuyerParty,SellerParty"
					  f"&$filter=BuyerParty/PartyID eq '{store_id}' or SellerParty/PartyID eq '{store_id}'")
		
		try:
			response = self.__get__(action_url)
			if response.status_code == 200:
				response_json = json.loads(response.text)
				return response_json["d"]["results"]
			else:
				logger.error(f"Failed to fetch sales orders for store {store_id}: {response.text}")
				return []
		except Exception as e:
			logger.error(f"Error fetching sales orders for store {store_id}: {str(e)}")
			raise
	
	def update_sales_order_status(self, sales_order_id: str, status: str) -> bool:
		'''
			Update sales order delivery status in SAP ByD
		'''
		# First get the sales order to get its ObjectID
		sales_order = self.get_sales_order_by_id(sales_order_id)
		if not sales_order:
			logger.error(f"Sales order {sales_order_id} not found")
			return False
		
		object_id = sales_order.get("ObjectID")
		if not object_id:
			logger.error(f"ObjectID not found for sales order {sales_order_id}")
			return False
		
		# Update the delivery status
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khsalesorder/SalesOrderCollection('{object_id}')"
		update_data = {
			"DeliveryStatusCode": status
		}
		
		try:
			self.refresh_csrf_token()
			response = self.session.patch(action_url, json=update_data, headers=self.auth_headers, auth=self.auth)
			if response.status_code == 204:  # PATCH typically returns 204 No Content on success
				logger.info(f"Sales order {sales_order_id} status updated to {status}")
				return True
			else:
				logger.error(f"Failed to update sales order status: {response.text}")
				return False
		except Exception as e:
			logger.error(f"Error updating sales order status: {str(e)}")
			return False
	
	def create_goods_issue_document(self, goods_issue_data: dict) -> dict:
		'''
			Create a goods issue document in SAP ByD with proper validation and structure
			Enhanced version with comprehensive validation and error handling
		'''
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khgoodsissue/GoodsIssueCollection"
		
		try:
			# Validate required fields for goods issue document
			required_fields = ["TypeCode", "PostingDate", "DocumentDate", "Item"]
			for field in required_fields:
				if field not in goods_issue_data:
					raise ValueError(f"Required field '{field}' missing from goods issue data")
			
			# Validate TypeCode is valid for store-to-store transfers
			valid_type_codes = ["01", "02", "03"]  # Common goods issue type codes
			if goods_issue_data["TypeCode"] not in valid_type_codes:
				raise ValueError(f"Invalid TypeCode '{goods_issue_data['TypeCode']}'. Must be one of: {valid_type_codes}")
			
			# Validate date format
			import datetime
			try:
				datetime.datetime.strptime(goods_issue_data["PostingDate"], "%Y-%m-%d")
				datetime.datetime.strptime(goods_issue_data["DocumentDate"], "%Y-%m-%d")
			except ValueError as e:
				raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")
			
			# Validate line items
			if not goods_issue_data["Item"] or not isinstance(goods_issue_data["Item"], list):
				raise ValueError("Goods issue must contain at least one line item")
			
			for i, item in enumerate(goods_issue_data["Item"]):
				# Validate required item fields
				required_item_fields = ["ProductID", "Quantity", "QuantityUnitCode", "SourceLogisticsAreaID"]
				for field in required_item_fields:
					if field not in item:
						raise ValueError(f"Required field '{field}' missing from line item {i+1}")
				
				# Validate quantity is positive
				try:
					quantity = float(item["Quantity"])
					if quantity <= 0:
						raise ValueError(f"Quantity must be positive for line item {i+1}: {quantity}")
				except (ValueError, TypeError):
					raise ValueError(f"Invalid quantity format for line item {i+1}: {item['Quantity']}")
				
				# Validate ProductID is not empty
				if not item["ProductID"].strip():
					raise ValueError(f"ProductID cannot be empty for line item {i+1}")
				
				# Validate SourceLogisticsAreaID is not empty
				if not item["SourceLogisticsAreaID"].strip():
					raise ValueError(f"SourceLogisticsAreaID cannot be empty for line item {i+1}")
			
			# Add default values for optional fields
			if "Note" not in goods_issue_data:
				goods_issue_data["Note"] = "Store-to-store transfer goods issue"
			
			# Ensure proper data types
			for item in goods_issue_data["Item"]:
				item["Quantity"] = str(item["Quantity"])  # Ensure quantity is string
				if "UnitPrice" in item:
					item["UnitPrice"] = str(item["UnitPrice"])
			
			logger.info(f"Creating goods issue document in SAP ByD with {len(goods_issue_data['Item'])} line items")
			
			self.refresh_csrf_token()
			response = self.__post__(action_url, json=goods_issue_data)
			
			if response.status_code == 201:
				logger.info(f"Goods issue document successfully created in SAP ByD.")
				response_data = response.json()
				
				# Validate response structure
				if not response_data or "d" not in response_data:
					raise Exception("Invalid response structure from SAP ByD")
				
				results = response_data.get("d", {}).get("results")
				if not results or "ObjectID" not in results:
					raise Exception("ObjectID not found in SAP ByD response")
				
				logger.info(f"Goods issue document created with ObjectID: {results['ObjectID']}")
				return response_data
				
			else:
				error_msg = f"Failed to create goods issue document: {response.text}"
				logger.error(error_msg)
				
				# Parse SAP error response for better error handling
				try:
					error_response = response.json()
					if "error" in error_response:
						sap_error = error_response["error"]
						if "message" in sap_error:
							error_msg = f"SAP ByD Error: {sap_error['message']['value']}"
				except:
					pass  # Use original error message if parsing fails
				
				raise Exception(error_msg)
				
		except ValueError as e:
			logger.error(f"Validation error creating goods issue document: {str(e)}")
			raise
		except Exception as e:
			logger.error(f"Error creating goods issue document: {str(e)}")
			raise
	
	def create_goods_issue(self, goods_issue_data: dict) -> dict:
		'''
			Create a goods issue in SAP ByD for store-to-store transfers
			Wrapper method that calls create_goods_issue_document for backward compatibility
		'''
		return self.create_goods_issue_document(goods_issue_data)
	
	def validate_goods_issue_requirements(self, goods_issue_data: dict) -> dict:
		'''
			Validate SAP ByD goods issue requirements and return validation results
		'''
		validation_results = {
			"is_valid": True,
			"errors": [],
			"warnings": []
		}
		
		try:
			# Check required header fields
			required_header_fields = {
				"TypeCode": "Goods issue type code",
				"PostingDate": "Posting date",
				"DocumentDate": "Document date",
				"Item": "Line items"
			}
			
			for field, description in required_header_fields.items():
				if field not in goods_issue_data or not goods_issue_data[field]:
					validation_results["errors"].append(f"Missing required field: {description} ({field})")
					validation_results["is_valid"] = False
			
			# Validate TypeCode
			if "TypeCode" in goods_issue_data:
				valid_type_codes = ["01", "02", "03", "04", "05"]
				if goods_issue_data["TypeCode"] not in valid_type_codes:
					validation_results["errors"].append(f"Invalid TypeCode '{goods_issue_data['TypeCode']}'. Valid codes: {valid_type_codes}")
					validation_results["is_valid"] = False
			
			# Validate dates
			import datetime
			for date_field in ["PostingDate", "DocumentDate"]:
				if date_field in goods_issue_data:
					try:
						datetime.datetime.strptime(goods_issue_data[date_field], "%Y-%m-%d")
					except ValueError:
						validation_results["errors"].append(f"Invalid {date_field} format. Use YYYY-MM-DD")
						validation_results["is_valid"] = False
			
			# Validate line items
			if "Item" in goods_issue_data:
				if not isinstance(goods_issue_data["Item"], list):
					validation_results["errors"].append("Item field must be a list")
					validation_results["is_valid"] = False
				elif len(goods_issue_data["Item"]) == 0:
					validation_results["errors"].append("At least one line item is required")
					validation_results["is_valid"] = False
				else:
					# Validate each line item
					for i, item in enumerate(goods_issue_data["Item"]):
						item_errors = self._validate_goods_issue_line_item(item, i + 1)
						validation_results["errors"].extend(item_errors)
						if item_errors:
							validation_results["is_valid"] = False
			
			# Check for warnings
			if "Note" not in goods_issue_data or not goods_issue_data["Note"]:
				validation_results["warnings"].append("Note field is empty - consider adding description")
			
			# Validate total quantities
			if "Item" in goods_issue_data and isinstance(goods_issue_data["Item"], list):
				total_items = len(goods_issue_data["Item"])
				if total_items > 100:
					validation_results["warnings"].append(f"Large number of line items ({total_items}) may impact performance")
			
		except Exception as e:
			validation_results["errors"].append(f"Validation error: {str(e)}")
			validation_results["is_valid"] = False
		
		return validation_results
	
	def _validate_goods_issue_line_item(self, item: dict, item_number: int) -> list:
		'''
			Validate individual goods issue line item
		'''
		errors = []
		
		# Required fields for line items
		required_fields = {
			"ProductID": "Product ID",
			"Quantity": "Quantity",
			"QuantityUnitCode": "Unit of measurement",
			"SourceLogisticsAreaID": "Source logistics area"
		}
		
		for field, description in required_fields.items():
			if field not in item or not str(item[field]).strip():
				errors.append(f"Line item {item_number}: Missing {description} ({field})")
		
		# Validate quantity
		if "Quantity" in item:
			try:
				quantity = float(item["Quantity"])
				if quantity <= 0:
					errors.append(f"Line item {item_number}: Quantity must be positive ({quantity})")
				if quantity > 999999:
					errors.append(f"Line item {item_number}: Quantity too large ({quantity})")
			except (ValueError, TypeError):
				errors.append(f"Line item {item_number}: Invalid quantity format ({item['Quantity']})")
		
		# Validate ProductID format
		if "ProductID" in item:
			product_id = str(item["ProductID"]).strip()
			if len(product_id) > 40:
				errors.append(f"Line item {item_number}: ProductID too long (max 40 characters)")
			if not product_id.replace("-", "").replace("_", "").isalnum():
				errors.append(f"Line item {item_number}: ProductID contains invalid characters")
		
		# Validate QuantityUnitCode
		if "QuantityUnitCode" in item:
			unit_code = str(item["QuantityUnitCode"]).strip()
			if len(unit_code) > 3:
				errors.append(f"Line item {item_number}: QuantityUnitCode too long (max 3 characters)")
		
		# Validate SourceLogisticsAreaID
		if "SourceLogisticsAreaID" in item:
			source_area = str(item["SourceLogisticsAreaID"]).strip()
			if len(source_area) > 20:
				errors.append(f"Line item {item_number}: SourceLogisticsAreaID too long (max 20 characters)")
		
		return errors
	
	def prepare_goods_issue_document(self, transfer_data: dict) -> dict:
		'''
			Prepare goods issue document data in the correct SAP ByD format
		'''
		try:
			# Extract required information
			goods_issue_data = {
				"TypeCode": transfer_data.get("type_code", "01"),  # Default to standard goods issue
				"PostingDate": transfer_data.get("posting_date"),
				"DocumentDate": transfer_data.get("document_date", transfer_data.get("posting_date")),
				"Note": transfer_data.get("note", "Store-to-store transfer goods issue"),
				"Item": []
			}
			
			# Process line items
			line_items = transfer_data.get("line_items", [])
			for item in line_items:
				line_item_data = {
					"ProductID": item.get("product_id"),
					"Quantity": str(item.get("quantity", 0)),
					"QuantityUnitCode": item.get("unit_of_measurement", "EA"),
					"SourceLogisticsAreaID": item.get("source_logistics_area"),
					"Note": item.get("note", "")
				}
				
				# Add optional fields if present
				if "sales_order_id" in item:
					line_item_data["SalesOrderID"] = str(item["sales_order_id"])
				if "sales_order_item_id" in item:
					line_item_data["SalesOrderItemID"] = item["sales_order_item_id"]
				if "unit_price" in item:
					line_item_data["UnitPrice"] = str(item["unit_price"])
				
				goods_issue_data["Item"].append(line_item_data)
			
			return goods_issue_data
			
		except Exception as e:
			logger.error(f"Error preparing goods issue document: {str(e)}")
			raise ValueError(f"Failed to prepare goods issue document: {str(e)}")
	
	def post_goods_issue(self, object_id: str) -> dict:
		'''
			Post a goods issue in SAP ByD
		'''
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khgoodsissue/PostGoodsIssue?ObjectID='{object_id}'"
		
		try:
			self.refresh_csrf_token()
			response = self.__post__(action_url)
			if response.status_code == 200:
				logger.info(f"Goods issue successfully posted.")
				return response.json()
			else:
				logger.error(f"Failed to post goods issue: {response.text}")
				raise Exception(f"Error from SAP: {response.text}")
		except Exception as e:
			logger.error(f"Error posting goods issue: {str(e)}")
			raise
	
	def complete_transfer_in_sap(self, sales_order_id: str, goods_issue_object_id: str = None) -> dict:
		'''
			Complete a store-to-store transfer in SAP ByD by updating sales order status
			and linking goods issue document
		'''
		try:
			# First get the sales order to get its ObjectID
			sales_order = self.get_sales_order_by_id(sales_order_id)
			if not sales_order:
				logger.error(f"Sales order {sales_order_id} not found")
				raise Exception(f"Sales order {sales_order_id} not found")
			
			object_id = sales_order.get("ObjectID")
			if not object_id:
				logger.error(f"ObjectID not found for sales order {sales_order_id}")
				raise Exception(f"ObjectID not found for sales order {sales_order_id}")
			
			# Update the delivery status to completely delivered
			action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khsalesorder/SalesOrderCollection('{object_id}')"
			update_data = {
				"DeliveryStatusCode": "3"  # Completely Delivered
			}
			
			# Add goods issue document reference if provided
			if goods_issue_object_id:
				update_data["GoodsIssueReference"] = goods_issue_object_id
			
			self.refresh_csrf_token()
			response = self.session.patch(action_url, json=update_data, headers=self.auth_headers, auth=self.auth)
			
			if response.status_code == 204:  # PATCH typically returns 204 No Content on success
				logger.info(f"Transfer completed for sales order {sales_order_id}")
				return {
					"success": True,
					"sales_order_id": sales_order_id,
					"object_id": object_id,
					"status": "Completely Delivered",
					"goods_issue_reference": goods_issue_object_id
				}
			else:
				logger.error(f"Failed to complete transfer: {response.text}")
				raise Exception(f"Error from SAP: {response.text}")
				
		except Exception as e:
			logger.error(f"Error completing transfer for sales order {sales_order_id}: {str(e)}")
			raise
	
	def link_goods_issue_to_sales_order(self, sales_order_id: str, goods_issue_object_id: str) -> bool:
		'''
			Link a goods issue document to a sales order in SAP ByD
		'''
		try:
			# Get the sales order
			sales_order = self.get_sales_order_by_id(sales_order_id)
			if not sales_order:
				logger.error(f"Sales order {sales_order_id} not found")
				return False
			
			object_id = sales_order.get("ObjectID")
			if not object_id:
				logger.error(f"ObjectID not found for sales order {sales_order_id}")
				return False
			
			# Update sales order with goods issue reference
			action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khsalesorder/SalesOrderCollection('{object_id}')"
			update_data = {
				"GoodsIssueReference": goods_issue_object_id,
				"LastChangeDateTime": timezone.now().strftime("%Y-%m-%dT%H:%M:%S")
			}
			
			self.refresh_csrf_token()
			response = self.session.patch(action_url, json=update_data, headers=self.auth_headers, auth=self.auth)
			
			if response.status_code == 204:
				logger.info(f"Goods issue {goods_issue_object_id} linked to sales order {sales_order_id}")
				return True
			else:
				logger.error(f"Failed to link goods issue to sales order: {response.text}")
				return False
				
		except Exception as e:
			logger.error(f"Error linking goods issue to sales order: {str(e)}")
			return False