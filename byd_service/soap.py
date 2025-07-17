import os
from requests import Session
from requests.auth import HTTPBasicAuth  # or HTTPDigestAuth, or OAuth1, etc.
from zeep import Client
from zeep.transports import Transport
from pathlib import Path
from dotenv import load_dotenv

from .authenticate import SAPAuthentication

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

# Initialize the authentication class
sap_auth = SAPAuthentication()


class SOAPServices:

	def __init__(self, ):
		"""
			Initialize the SOAP client and authenticate with SAP.
		"""
		self.client = None
		self.soap_client = None

	def connect(self, ):
		transport = Transport(timeout=5, operation_timeout=3)
		client = Client(self.wsdl_path, transport=transport)
		client.transport.session.auth = sap_auth.http_authentication()

		self.client = client