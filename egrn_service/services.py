import os
import logging
from requests import get, post
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

class Middleware:
	'''
		Services provided by the middleware system.
	'''
	host = os.getenv('MIDDLEWARE_HOST')
	user_id = os.getenv('MIDDLEWARE_USER')
	password = os.getenv('MIDDLEWARE_PASS')
	headers = {}
	
	def __init__(self):
		self.authenticate()
		
	def authenticate(self):
		'''
		    Authenticate with the middleware service to obtain an access token.
		'''
		auth_url = f'{self.host}/api/v1/authenticate'
		auth_data = {
			"username": self.user_id,
			"password": self.password
		}
		response = post(auth_url, json=auth_data)
		if response.status_code == 200:
			self.headers = {
				'Authorization': f'Bearer {response.json().get("data",{}).get("access")}'
			}
		else:
			logging.error(f"Authentication failed: {response.text}")

	def get_store(self, *args, **kwargs):
		'''
			Retrieve store details from the middleware service.
			Args:
				kwargs (dict): Key-value pairs to be appended to the URL query parameters which identifies the store to retrieve.
		'''
		params = "&".join([f'{key}={value}' for key, value in kwargs.items()])
		headers = self.headers
		url = f'{os.getenv("MIDDLEWARE_HOST")}/api/v1/store'
		url = f'{url}?{params}' if params else url
		
		try:
			response = get(url, headers=headers)
			if response.status_code == 200:
				return response.json()['data']
		except Exception as e:
			logging.error(f"Error fetching store ({url}): {str(e)}")
		
		return None