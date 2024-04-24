import logging
from celery import shared_task
from django.core.mail import EmailMessage


@shared_task
def send_email_async(html_content):
	try:
		# Send the HTML content via email
		email = EmailMessage(
			'Your Goods Received Note',
			html_content,
			'network@foodconceptsplc.com',
			['davynathaniel@gmail.com', 'oguntoyeadebola21@gmail.com']
		)
		email.content_subtype = 'html'
		email.send()
		return True
	except Exception as e:
		logging.error(e)
		return False
