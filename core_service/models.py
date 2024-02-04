import os
from dotenv import load_dotenv
import logging
from django.db import models
from django.contrib.auth.models import AbstractUser
import hashlib, random
from django.db import IntegrityError
from django.core.mail import EmailMessage

load_dotenv()


class CustomUser(AbstractUser):
	def __str__(self):
		return f"{self.first_name} {self.last_name} ({self.email})"


class VendorProfile(models.Model):
	user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='vendor_profile')
	phone = models.CharField(max_length=20, null=True, blank=True)
	created_on = models.DateTimeField(auto_now_add=True)
	byd_internal_id = models.CharField(max_length=20, unique=True, blank=False, null=False)
	byd_metadata = models.JSONField(default=dict)

	def __str__(self):
		return f"{self.user.first_name}'s Profile"


class TempUser(models.Model):
	"""docstring for TempUser"""
	_ID_TYPES = {
		("email", "EMAIL"),
		("phone", "PHONE")
	}

	identifier = models.CharField(max_length=255, null=False, blank=False, unique=True)
	id_type = models.CharField(max_length=7, null=False, blank=False, choices=_ID_TYPES)
	token = models.CharField(max_length=255, null=False, blank=False, editable=False)
	verified = models.BooleanField(default=False)
	account_created = models.BooleanField(default=False)
	created_on = models.DateTimeField(auto_now_add=True)
	byd_metadata = models.JSONField(default=dict)

	def save(self, *args, **kwargs):

		self.token = self.__generate_auth_token__()

		if not self.verified and not self.account_created:
			#If it's an update, update the token
			kwargs["update_fields"].update({"token": self.token}) if kwargs.get("update_fields") else None

			try:
				self.__send_auth_email__() if self.id_type == 'email' else None
				self.__send_auth_sms__() if self.id_type == 'phone' else None

			except Exception as e:
				raise e

		elif self.verified and not self.account_created:
			print("send verification success email")

		elif self.verified and self.account_created:
			print("send account created email")

		super(TempUser, self).save(*args, **kwargs)

	def __generate_auth_token__(self,):
		t = hashlib.sha256()
		o = random.randint(1000, 999999)
		k = hex(id(t))
		e = str(o) + k
		n = str.encode(e)
		t.update(n)

		return t.hexdigest()

	def __send_auth_email__(self, ):
		sender_name = "Food Concepts Plc"
		email_from = os.getenv("EMAIL_USER")
		merchant_name = str(self.byd_metadata["BusinessPartner"]["BusinessPartnerFormattedName"])
		# email_to = self.identifier.strip().split(" ")
		email_to = "davynathaniel@gmail.com oguntoyeadebola21@gmail.com".split(" ")
		email_subject = f"Complete your account setup"
		email_body = ""

		id_hash = hashlib.sha256()
		hash_concat = f'{self.identifier}{self.id_type}{self.byd_metadata["BusinessPartner"]["BusinessPartnerFormattedName"]}{self.token}'
		id_hash.update(str.encode(hash_concat))

		verification_link = f'{os.getenv("DEV_HOST")}/sign-up?{id_hash.hexdigest()}={self.token}'

		template_file = os.getenv("VERIFICATION_EMAIL_TEMPLATE")
		try:
			with open(template_file, 'r', encoding='utf-8') as template:
				content = template.read()
		except FileNotFoundError as e:
			logging.error(f"Template file not found in {template_file}")
			return False
		except Exception as e:
			logging.error(f"Template file exception {e}")
			return False

		#Insert the message into the template
		content = content.replace("{{MERCHANT_NAME}}", merchant_name)
		content = content.replace("{{LINK}}", verification_link)
		email_body = content

		email = EmailMessage(
			subject=email_subject, 
			body=email_body, 
			from_email=f"{sender_name} <{email_from}>", 
			to=email_to
		)

		email.content_subtype = 'html'

		logging.debug(f"{sender_name} <{email_from}>")
		
		try:
			email.send()
			return True
		except Exception as e:
			logging.error(f"An error occurred sending an email: {e}")
			raise e

		return False

	def __send_sms__(self, ):
		pass

	def __str__(self,):
		return f'{self.identifier}\'s {self.id_type}'

