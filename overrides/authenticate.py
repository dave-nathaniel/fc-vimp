from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from rest_framework.authentication import BaseAuthentication, BasicAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
import base64
import binascii

class CombinedAuthentication(BaseAuthentication):
	def authenticate(self, request):
		jwt_auth = JWTAuthentication()
		adfs_auth = AdfsAccessTokenAuthentication()

		# Try to authenticate using JWTAuthentication
		try:
			user, jwt_token = jwt_auth.authenticate(request)
			if user is not None:
				return (user, jwt_token)
		except AuthenticationFailed:
			pass

		# If JWTAuthentication fails, try to authenticate using AdfsAccessTokenAuthentication
		try:
			print("Trying ADFS Authentication")
			user, adfs_token = adfs_auth.authenticate(request)
			if user is not None:
				return (user, adfs_token)
		except AuthenticationFailed:
			pass

		# If both authentication methods fail, return None
		return None

	def authenticate_header(self, request):
		return 'Bearer'


class CombinedWithBasicAuthentication(BaseAuthentication):
	"""
	Combined authentication supporting JWT, ADFS, and HTTP Basic Auth.
	Tries authentication methods in order: JWT -> ADFS -> Basic Auth
	"""

	def authenticate(self, request):
		# Try JWT first
		jwt_auth = JWTAuthentication()
		try:
			result = jwt_auth.authenticate(request)
			if result is not None:
				user, jwt_token = result
				if user is not None:
					return (user, jwt_token)
		except (AuthenticationFailed, Exception):
			pass

		# Try ADFS
		adfs_auth = AdfsAccessTokenAuthentication()
		try:
			result = adfs_auth.authenticate(request)
			if result is not None:
				user, adfs_token = result
				if user is not None:
					return (user, adfs_token)
		except (AuthenticationFailed, Exception):
			pass

		# Try Basic Authentication
		auth_header = request.META.get('HTTP_AUTHORIZATION', '')

		if auth_header.startswith('Basic '):
			try:
				# Decode Basic Auth credentials
				auth_decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
				username, password = auth_decoded.split(':', 1)

				# Authenticate user
				user = authenticate(username=username, password=password)

				if user is not None and user.is_active:
					return (user, None)
				else:
					raise AuthenticationFailed('Invalid username or password')

			except (binascii.Error, UnicodeDecodeError, ValueError):
				raise AuthenticationFailed('Invalid Basic Auth header')

		# All authentication methods failed
		return None

	def authenticate_header(self, request):
		"""
		Return authentication header hint for 401 responses
		"""
		return 'Basic realm="API", Bearer'
