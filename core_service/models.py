import os
import logging

import pyotp
import hashlib, random
from PIL import Image, ImageDraw, ImageFont
from django_q.tasks import async_task
from django.contrib.auth.hashers import make_password
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core import signing
from .services import send_sms
from .helpers import base64_to_image
from dotenv import load_dotenv


load_dotenv()


class CustomUser(AbstractUser):
	secret = models.CharField(max_length=255, null=True, blank=True)
	
	def make_secret(self, key: str, secret=None) -> str:
		'''
			Generate and set a secret key for the user; this will be used to generate OTP codes.
		'''
		secret = secret or pyotp.random_base32()
		signer = signing.Signer(salt=key)
		return signer.sign_object(secret)
		
	def get_secret(self, key: str) -> str:
		'''
			Retrieve and return the secret key for the user; this will be used to generate OTP codes.
		'''
		signer = signing.Signer(salt=key)
		try:
			return signer.unsign_object(self.secret)
		except signing.BadSignature:
			raise ValueError(f"Unable to decode hash {self.secret}")
	
	def save(self, *args, **kwargs):
		# Ensure the password is hashed before saving
		if self.pk is None or not self.password.startswith('pbkdf2_sha256$'):
			self.password = make_password(self.password)
		super().save(*args, **kwargs)
	
	def __str__(self):
		return f"{self.first_name} {self.last_name} ({self.email})"
	
	class Meta:
		verbose_name_plural = 'Users'


class TempUser(models.Model):
	"""docstring for TempUser"""
	_ID_TYPES = (
		("email", "EMAIL"),
		("phone", "PHONE")
	)
	
	identifier = models.CharField(max_length=255, null=False, blank=False, unique=True)
	id_type = models.CharField(max_length=7, null=False, blank=False, choices=_ID_TYPES)
	token = models.CharField(max_length=255, null=False, blank=False, editable=False)
	verified = models.BooleanField(default=False)
	account_created = models.BooleanField(default=False)
	created_on = models.DateTimeField(auto_now_add=True)
	byd_metadata = models.JSONField(default=dict)
	
	def save(self, *args, **kwargs):
		
		self.token = self.__generate_auth_token__()
		
		id_hash = hashlib.sha256()
		hash_concat = f'{self.identifier}{self.id_type}{self.byd_metadata["BusinessPartner"]["BusinessPartnerFormattedName"]}{self.token}'
		id_hash.update(str.encode(hash_concat))
		
		if not self.verified and not self.account_created:
			# If it's an update, update the token
			kwargs["update_fields"].update({"token": self.token}) if kwargs.get("update_fields") else None
			
			try:
				self.__send_auth_email__(id_hash) if self.id_type == 'email' else None
				self.__send_auth_sms__(id_hash) if self.id_type == 'phone' else None
			
			except Exception as e:
				raise e
		
		elif self.verified and not self.account_created:
			print("send verification success email")
		
		elif self.verified and self.account_created:
			print("send account created email")
		
		return super().save(*args, **kwargs)
	
	def __generate_auth_token__(self, ):
		t = hashlib.sha256()
		o = random.randint(1000, 999999)
		k = hex(id(t))
		e = str(o) + k
		n = str.encode(e)
		t.update(n)
		
		return t.hexdigest()
	
	def __send_auth_email__(self, id_hash):
		async_task('vimp.tasks.send_vendor_setup_email', {
			"instance": self,
			"id_hash": id_hash.hexdigest(),
		})
	
	def __send_auth_sms__(self, id_hash):
		sender_name = os.getenv("SMS_FROM")
		verification_link = f'{self.token}'
		message = f"Your vendor verification code is {verification_link[:5]}."
		recipient = ["08101225426"]
		
		return send_sms(recipient, sender_name, message)
	
	def __str__(self, ):
		return f'{self.identifier}\'s {self.id_type}'
	
	class Meta:
		verbose_name_plural = 'Temp Users'


class VendorProfile(models.Model):
	user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, null=True, related_name='vendor_profile')
	phone = models.CharField(max_length=20, null=True, blank=True)
	created_on = models.DateTimeField(auto_now_add=True)
	byd_internal_id = models.CharField(max_length=20, unique=True, blank=False, null=False)
	byd_metadata = models.JSONField(default=dict)
	vendor_settings = models.JSONField(default=dict, blank=True)
	
	def __default_settings__(self):
		default_settings = {}
		# Default invoice color
		default_settings["invoice_color"] = "#000000"
		try:
			default_settings["logo"] = self.generate_vendor_logo()
		except Exception as e:
			logging.error(f"An error occurred generating the logo: {e}")
		
		return default_settings
	
	def save(self, *args, **kwargs):
		# if this vendor has no settings, add the default settings; but make sure a user has also been assigned too
		if not self.vendor_settings and self.user:
			self.vendor_settings = self.__default_settings__()
		# If the data has been passed in, update accordingly
		data = kwargs.pop('data') if kwargs.get('data') else {}
		# If the vendor settings have been passed, merge with existing settings
		if data.get("vendor_settings"):
			# If the logo has been passed in, update it
			if data["vendor_settings"].get("logo"):
				try:
					# We are expecting a base64 string, convert it to an image and save it
					base64_to_image(data["vendor_settings"]["logo"], os.path.join(settings.MEDIA_ROOT, 'logos'),
									f'{self.user.username}_logo.png')
					data["vendor_settings"]["logo"] = f'{os.getenv("HOST")}/media/logos/{self.user.username}_logo.png'
				except Exception as e:
					logging.error(f"An error occurred generating the logo: {e}")
					raise e
			data["vendor_settings"] = {**self.vendor_settings, **data.get('vendor_settings', {})}
		# Set the attributes with the keys from the data
		for key, value in data.items():
			setattr(self, key, value)
		# Return the updated instance
		return super().save(*args, **kwargs)
	
	def generate_vendor_logo(self, ):
		# Get user's name
		name = self.user.first_name
		# Choose a font and font size
		font_path = os.path.join(settings.BASE_DIR, 'static', 'Montserrat.ttf')
		font = ImageFont.truetype(font_path, size=30)
		# Calculate text size and position
		text_width, text_height = font.getsize(name)
		# Create an Image object with white background
		image = Image.new("RGB", (text_width, text_height), "white")
		text_x = (image.width - text_width) // 2
		text_y = (image.height - text_height) // 2
		# Initialize ImageDraw object
		draw = ImageDraw.Draw(image)
		# Draw text on the image
		draw.text((text_x, text_y), name, fill="black", font=font)
		# Set the logo path
		logos_dir = os.path.join(settings.MEDIA_ROOT, 'logos')
		# If the logos directory doesn't exist, create it'
		if not os.path.exists(logos_dir):
			os.makedirs(logos_dir)
		# Save the image to a path
		logo_path = os.path.join(logos_dir, f'{self.user.username}_logo.png')
		image.save(logo_path)
		# Return the path to the image
		return f'{os.getenv("HOST")}/media/logos/{self.user.username}_logo.png'
	
	def __str__(self):
		if self.user:
			return f"{self.byd_internal_id} | {self.user.email}"
		return f"{self.byd_internal_id}"
	
	class Meta:
		verbose_name_plural = 'Vendor Profiles'


class LedgerAccount(models.Model):
	...