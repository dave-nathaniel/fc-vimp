import os
from requests import auth, post, get, Session
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

class SAPAuthentication:
	
	'''
		Authentication class for SAP systems
	'''
	
	# SAP Base URL
	endpoint = os.getenv('SAP_URL')
	
	def __init__(self, username: str = None, password: str = None):
		'''
            Initialize the authentication class with username and password.
        '''
		self.username = username or os.getenv('SAP_USER')
		self.password = password or os.getenv('SAP_PASS')
		
	def http_authentication(self, cls: object = None) -> object:
		'''
			Returns an HTTPBasicAuth object for SAP authentication.
		'''
		def get_session(auth) -> tuple:
			'''
				Retrieves and returns the CSRF token for the SAP system.
			'''
			action_url = f"{self.endpoint}/sap/byd/odata/cust/v1/khpurchaseorder/"
			s = Session()
			headers = {"x-csrf-token": "fetch"}
			response = s.get(action_url, auth=auth, headers=headers)
			if response.status_code == 200:
				auth_headers = {
					'x-csrf-token': response.headers.get('x-csrf-token', '')
				}
				return s, auth_headers, auth
			else:
				raise ValueError(f"Failed to fetch CSRF token. Status code: {response.status_code}, Response: {response.text}")
		
		# Set the http_auth object for authentication
		# Return the http_auth object for authentication
		authentication = auth.HTTPBasicAuth(self.username, self.password)
		# If this method was used as a decorator, return the class with the session and auth_headers attributes
		if cls:
			cls.session, cls.auth_headers, cls.auth = get_session(authentication)
			return cls
		# Otherwise, return the HTTPBasicAuth object
		return authentication