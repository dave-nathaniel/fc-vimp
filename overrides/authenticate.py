from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication

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
