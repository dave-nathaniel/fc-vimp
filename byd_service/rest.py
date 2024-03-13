import os
import json
from requests import get, post, Session
from requests.auth import HTTPBasicAuth
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)


class RESTServices:
	endpoint = os.getenv('SAP_URL')
	username = os.getenv('SAP_USER')
	password = os.getenv('SAP_PASS')

	def __init__(self, ):
		self.auth = None
		self.session = None

		self.connect()

	def connect(self, ):
		self.auth = HTTPBasicAuth(self.username, self.password)

	def get_vendor_by_id(self, vendor_id, id_type='email'):
		action_url = f'{self.endpoint}/sap/byd/odata/cust/v1/khbusinesspartner/CurrentDefaultAddressInformationCollection?$format=json&$expand=EMail,BusinessPartner,ConventionalPhone,MobilePhone&$select=EMail,BusinessPartner,ConventionalPhone,MobilePhone&$top=1'
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
				return results[0]

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
						   f"Supplier/SupplierPostalAddress,PurchasingUnit/PurchasingUnitName,"
						   f"EmployeeResponsible/EmployeeResponsibleName,BillToParty/BillToPartyName,"
						   f"BuyerParty/BuyerPartyName,PaymentTerms,Notes,AttachmentFolder,"
						   f"ApproverParty/ApproverPartyName,"
						   f"Item/ItemShipToLocation/DeliveryAddress/DeliveryAddressName,"
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
