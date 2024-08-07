import os
import logging
from requests import get, post
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

def get_store_from_middleware(*args, **kwargs):
	'''
		Retrieve store details from the middleware service.
		Args:
            kwargs (dict): Key-value pairs to be appended to the URL query parameters which identifies the store to retrieve.
	'''
	params = "&".join([f'{key}={value}' for key, value in kwargs.items()])
	url = f'{os.getenv("MIDDLEWARE_HOST")}/api/v1/store'
	url = f'{url}?{params}' if params else url
	
	try:
		response = get(url)
		if response.status_code == 200:
			return response.json()['data']
	except Exception as e:
		logging(f"Error: {e}")
	
	return None