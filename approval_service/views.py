from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from rest_framework import status
from rest_framework.decorators import permission_classes, authentication_classes, api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from overrides.rest_framework import APIResponse
from .models import Keystore
from invoice_service.models import Invoice


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
		'''
			Creates a new Keystore for the authenticated user.
		'''
		...



@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def sign_signable_view(request, target_class):
	'''
		Signs a signable object.
	'''
	signable_class_mapping = {
		'invoice': {
			"class": Invoice,
			"app_label": "invoice_service",
		}
	}
	
	# If the signable class does not exist, return a 404
	if target_class not in signable_class_mapping:
		return APIResponse(f"A signable object of type {signable_class} was not found.", status=status.HTTP_404_NOT_FOUND)
	
	signable_class = signable_class_mapping[target_class].get("class")
	signable_app_label = signable_class_mapping[target_class].get("app_label")
	signable = signable_class.objects.get(id=request.data['signable_id'])
	
	if not request.user.has_perm(f"{signable_app_label}.can_sign_signable"):
		return APIResponse(f"You do not have permission to sign this {signable_class} object.", status=status.HTTP_403_FORBIDDEN)
	
	signable.sign(request)
	return APIResponse(message="Ok.", status=status.HTTP_200_OK)
	