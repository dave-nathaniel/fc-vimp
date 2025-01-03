import os
import json
from requests import get
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)


class RESTServices:
	'''
	    RESTful API for interacting with SAP's ByD system
	'''
	endpoint = os.getenv('SAP_URL')
	
	def __init__(self, ):
		from .authenticate import HTTPAuth
		
		self.auth = HTTPAuth()

	def get_vendor_by_id(self, vendor_id, id_type='email'):
		action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khbusinesspartner/CurrentDefaultAddressInformationCollection?$format=json&$expand=EMail,BusinessPartner,ConventionalPhone,MobilePhone&$select=EMail,BusinessPartner,ConventionalPhone,MobilePhone&$top=10"
		query_url = f"{action_url}&$filter=EMail/URI eq '{vendor_id}'"

		if id_type == 'phone':
			vendor_id = vendor_id.strip()[-10:]
			query_url = f"{action_url}&$filter=substringof('{vendor_id}',ConventionalPhone/NormalisedNumberDescription)"

		# Make a request with HTTP Basic Authentication
		response = get(query_url, auth=self.auth)

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
		response = get(action_url, auth=self.auth)

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
		response = get(action_url, auth=self.auth)

		if response.status_code == 200:
			try:
				response_json = json.loads(response.text)
				results = response_json["d"]["results"]
				return results[0] if results else False
			except Exception as e:
				raise e

		return False
	
	def create_order_receipt(self, ):
		...
