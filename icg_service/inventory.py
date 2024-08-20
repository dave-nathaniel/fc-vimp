import os
import logging
from requests import post
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

base_url = os.getenv('ICG_URL')

class StockManagement:
	
	auth_token = None
	auth_headers =  None
	api_url = f'{base_url}/api/FoodConcept'
	def __init__(self, ):
		from icg_service.authenticate import JWTAuth
		# Authenticate with the ICG service and get the JWT token
		self.auth_token = JWTAuth()
		# Set the authentication headers for the API requests
		self.auth_headers = {
			'Authorization': f'Bearer {self.auth_token}',
			'Content-Type': 'application/json'
		}
	
	def create_purchase_order(self, order_details: object, order_items: list) -> bool:
		'''
			Send a request to the PurchaseOrder endpoint to create a new purchase order.
			Params:
				order_details (dict): The details of the purchase order.
				order_items (list): The items in the purchase order.
			Returns: True if the purchase order request is successful, False otherwise.
		'''
		create_po_endpoint = f'{self.api_url}/PurchaseOrder'
		po_data = {
			"order": order_details,
			"itemDetails": order_items
		}
		# Make a POST request to the API endpoint. Fail silently if an error occurs with the request and return False.
		try:
			# Make a POST request to the API endpoint
			response = post(create_po_endpoint, json=po_data, headers=self.auth_headers)
			# Throw an exception if the response status code is not 200 (this exception is absorbed by the except block)
			if response.status_code != 200:
				raise Exception(f"The purchase order request failed with status code {response.status_code}")
		except Exception as e:
			logging.error(f"An error occurred while creating the purchase order: {e}")
			return False
		# If the request is successful, return True
		return True