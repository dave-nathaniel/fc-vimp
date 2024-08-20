import os
from requests.auth import HTTPBasicAuth
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

def HTTPAuth(username=os.getenv('SAP_USER'), password=os.getenv('SAP_PASS')):
	return HTTPBasicAuth(username, password)