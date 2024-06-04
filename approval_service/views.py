from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from overrides.rest_framework import APIResponse
from .models import Keystore


class KeystoreAPIView(APIView):
	"""
		Manage a signatories public key.
	"""
	authentication_classes = [AdfsAccessTokenAuthentication]
	permission_classes = (IsAuthenticated,)
	
	def get(self, request):
		'''
			Returns the public key of the authenticated user.
		'''
		try:
			keystore = Keystore.objects.get(user=request.user)
		except Keystore.DoesNotExist:
			return APIResponse(f"A Keystore was not found for this user.", status=status.HTTP_404_NOT_FOUND)
		
		return APIResponse(keystore.public_key, status=status.HTTP_200_OK)

	def post(self, request):
		pass