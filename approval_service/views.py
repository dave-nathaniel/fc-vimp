from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from rest_framework import status
from rest_framework.decorators import permission_classes, authentication_classes, api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from overrides.rest_framework import APIResponse
from .models import Keystore
from invoice_service.models import Invoice
from invoice_service.serializers import InvoiceSerializer
from django.core.exceptions import ObjectDoesNotExist


def get_signable_class(target_class: str) -> object:
	# Map signable classes to their corresponding Django models and app labels.
	signable_class_mapping = {
		'invoice': {
			"class": Invoice,
			"app_label": "invoice_service",
			"serializer": InvoiceSerializer,
		}
	}
	# If the signable class exists, return the corresponding Django model and app label
	if target_class in signable_class_mapping:
		return signable_class_mapping[target_class]
	# Return False if the signable class does not exist
	return False


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
def sign_signable_view(request, target_class, object_id):
	'''
		Signs a signable object, identified by the target class.
	'''
	# Get the signable class being signed in this request.
	target = get_signable_class(target_class)
	# If the signable class does not exist, return a 404
	if target:
		# Get the Django model and app label for the signable class.
		signable_class, signable_app_label = target.get("class"), target.get("app_label")
		# Check if the authenticated user has permission to sign the signable object. If not, return a 403 error.
		if not request.user.has_perm(f"{signable_app_label}.can_sign_signable"):
			return APIResponse(f"You do not have permission to sign this {signable_class} object.", status=status.HTTP_403_FORBIDDEN)
		# Try to get the signable object with the provided ID. If it does not exist, return an error message.
		try:
			signable = signable_class.objects.get(id=object_id)
		except ObjectDoesNotExist:
			return APIResponse(f"No {target_class} found with ID {request.data['signable_id']}.", status=status.HTTP_404_NOT_FOUND)
		try:
			# Sign the signable object and return a success message.
			signable.sign(request)
		except PermissionError:
			return APIResponse(f"You do not have permission to sign this {signable_class} object.", status=status.HTTP_403_FORBIDDEN)
		except Exception as e:
			return APIResponse(f"Internal Error: {e}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
		
		return APIResponse(message="Successful.", status=status.HTTP_200_OK)
	# Return a 404 if the signable class does not exist
	return APIResponse(f"A signable object of type {target_class} was not found.", status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def get_signable_view(request, target_class):
	'''
	    Returns a paginated list of signable objects for the authenticated user.
	    This method gets all the signable objects that are to be signed by the current role of the authenticated user.
	'''
	# Get the signable class being signed in this request.
	target = get_signable_class(target_class)
	# If the signable class does not exist, return a 404
	if target:
		# Get the Django model and app label for the signable class.
		signable_class, signable_app_label, signable_serializer = target.get("class"), target.get("app_label"), target.get("serializer")
		# Filter the users permissions for permissions relevant to the signable object.
		relevant_permissions = [p[1] for p in filter(
			lambda x: x[0] == signable_app_label,
			[x.split('.') for x in request.user.get_all_permissions()]
		)]
		# Get the signable objects that is pending signature from the role of the authenticated user.
		pending_signables = signable_class.objects.filter(current_pending_signatory__in=relevant_permissions)
		serialized_pending_signables = signable_serializer(pending_signables, many=True).data
		return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=serialized_pending_signables)
	# Return a 404 if the signable class does not exist
	return APIResponse(f"A signable object of type {target_class} was not found.", status=status.HTTP_404_NOT_FOUND)
	
	
	
	