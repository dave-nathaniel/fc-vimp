import os
import json
import logging
from requests import get, post
from pathlib import Path
from dotenv import load_dotenv

from .authenticate import SAPAuthentication

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

logger = logging.getLogger()

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
	
	def __init__(self, ):
		pass
	
	def __get__(self, *args, **kwargs):
		return self.session.get(*args, **kwargs, auth=self.auth)
	
	def __post__(self, *args, **kwargs):
		'''
			This method makes a POST request to the given URL with CSRF protection
		'''
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
	
	# Supplier Invoice Creation
	def create_supplier_invoice(self, invoice_data: dict) -> dict:
		'''
            Create a Supplier Invoice in SAP ByD
        '''
		# Action URL for creating a Goods and Service Acknowledgement (GRN) in SAP ByD
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khsupplierinvoice/SupplierInvoiceCollection"
		
		try:
			# Make a request with HTTP Basic Authentication
			response = self.__post__(action_url, json=invoice_data)
			if response.status_code == 201:
				logging.info(f"Invoice successfully created in SAP ByD.")
				return response.json()
			else:
				logging.error(f"Failed to create Invoice: {response.text}")
				raise Exception(f"{response.text}")
		except Exception as e:
			raise Exception(f"{e}")
