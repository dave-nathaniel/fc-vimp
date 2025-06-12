import os
import json
import logging
import time
from requests import get, post
from pathlib import Path
from dotenv import load_dotenv

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