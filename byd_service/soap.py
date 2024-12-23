import os
from requests import Session
from requests.auth import HTTPBasicAuth  # or HTTPDigestAuth, or OAuth1, etc.
from zeep import Client
from zeep.transports import Transport
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)


class SOAPServices:

    soap_endpoint = 'https://my350679.sapbydesign.com/sap/bc/srt/scs/sap/manageaccountingentryin'
    wsdl_path = os.path.join(Path(__file__).resolve().parent.parent, 'manageaccountingentryin.wsdl')
    username = os.getenv('SAP_USER')
    password = os.getenv('SAP_PASS')

    def __init__(self, ):
        self.client = None
        self.soap_client = None

    def connect(self, ):
        transport = Transport(timeout=5, operation_timeout=3)
        client = Client(self.wsdl_path, transport=transport)
        client.transport.session.auth = HTTPBasicAuth(self.username, self.password)

        # Access the services (operations) provided by the SOAP endpoint
        soap_client = client.create_service("{http://sap.com/xi/AP/FinancialAccounting/Global}binding", self.soap_endpoint)

        self.client, self.soap_client = client, soap_client