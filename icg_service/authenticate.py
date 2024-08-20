import os
from requests import post
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

base_url = os.getenv('ICG_URL')

def JWTAuth(username=os.getenv('ICG_USER'), password=os.getenv('ICG_PASS')):
	'''
		Authenticate with the ICG service and return the JWT token
	'''
	url = f'{base_url}/token'
	headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
	data = {
		'username': username,
		'password': password,
		'grant_type': 'password'
	}
	response = post(url, data=data, headers=headers)
	if response.status_code == 200:
		return response.json()['access_token']
	return None