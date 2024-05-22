# API view to update Vendor Profile
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from rest_framework.views import APIView
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


class PermissionTestsView(APIView):
	authentication_classes = [AdfsAccessTokenAuthentication]
	permission_classes = (IsAuthenticated,)
	def get(self, request):
		print(request.user)
		return APIResponse('Authenticated', status.HTTP_200_OK)