import os, sys
from pprint import pprint
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()


def send_sms(number_list, sender_name, message):
	host = os.getenv("SMS_HOST")
	url = f'https://{host}/'
	username = os.getenv("SMS_USERNAME")
	password = os.getenv("SMS_PASSWORD")

	headers = {
		"Host": host,
		"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
	}

	session = requests.Session()
	get_cookies = session.get(url, headers=headers)
	response = session.get(url, headers=headers)

	if response.status_code == 200:
		token = BeautifulSoup(response.text, 'html.parser').find(attrs={"name": "captcha"})
		token = token["value"]

		login_data = {
			"username": username,
			"password": password,
			"captcha": token
		}

		session.cookies = session.post(f"{url}", headers=headers, data=login_data, allow_redirects=False).cookies

		sms_page = session.get(f"{url}bulksms/", headers=headers)

		token = BeautifulSoup(sms_page.text, 'html.parser').find(attrs={"name": "browser_reload"})
		token = token["value"]

		sms_form_data = {
			'autofocus': '#mobiles',
			'action': '',
			'schedule': '',
			'browser_reload': token,
			'mobile-list': 'mobile-text',
			'mobiles': "\r\n".join(number_list),
			'sender': sender_name,
			'message': message,
			'date': '',
			'time': '',
			'send-btn': '@',
		}

		sms_form_data = {key: (None, str(value)) for key, value in sms_form_data.items()}

		do_send = session.post(f"{url}bulksms/", headers=headers,files=sms_form_data)

		if do_send.status_code == 200:
			print(f"SMS sent to {chr(10).join(number_list)}")
			return True
		else:
			print("Error sending SMS", do_send.status_code)
	else:
		print("failed:", response.status_code)

	session.close()
	
	return False