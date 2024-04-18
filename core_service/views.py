# API view to update Vendor Profile
from rest_framework import status
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import CustomTokenObtainPairSerializer
from overrides.rest_framework import APIResponse


# Custom Token Obtain Pair View
class CustomTokenObtainPairView(TokenObtainPairView):
	# Override the default serializer class
	serializer_class = CustomTokenObtainPairSerializer
	# Override the default permission classes
	def post(self, request, *args, **kwargs):
		response = super().post(request, *args, **kwargs)
		return APIResponse('Authenticated', status.HTTP_200_OK, data=response.data)
