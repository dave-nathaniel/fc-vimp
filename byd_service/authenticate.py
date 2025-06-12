import os
from requests import auth, post, get, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

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
			
			# Configure retry strategy
			retry_strategy = Retry(
				total=3,
				backoff_factor=1,
				status_forcelist=[500, 502, 503, 504]
			)
			adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
			s.mount("http://", adapter)
			s.mount("https://", adapter)
			
			headers = {"x-csrf-token": "fetch"}
			try:
				response = s.get(action_url, auth=auth, headers=headers, timeout=30)
				if response.status_code == 200:
					auth_headers = {
						'x-csrf-token': response.headers.get('x-csrf-token', '')
					}
					return s, auth_headers, auth
				else:
					logger.error(f"Failed to fetch CSRF token. Status code: {response.status_code}, Response: {response.text}")
					raise ValueError(f"Failed to fetch CSRF token. Status code: {response.status_code}")
			except Exception as e:
				logger.error(f"Error during session initialization: {str(e)}")
				raise
		
		# Set the http_auth object for authentication
		authentication = auth.HTTPBasicAuth(self.username, self.password)
		# If this method was used as a decorator, return the class with the session and auth_headers attributes
		if cls:
			cls.session, cls.auth_headers, cls.auth = get_session(authentication)
			return cls
		# Otherwise, return the HTTPBasicAuth object
		return authentication