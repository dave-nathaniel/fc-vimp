from django.contrib.contenttypes.models import ContentType
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from rest_framework import status
from rest_framework.decorators import permission_classes, authentication_classes, api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from invoice_service.serializers import InvoiceSerializer
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from .models import Keystore, Signature
from .serializers import SignatureSerializer
from invoice_service.models import Invoice
from overrides.rest_framework import APIResponse, CustomPagination

paginator = CustomPagination()

def get_signable_class(target_class: str) -> object:
	# Map signable classes to their corresponding Django models and app labels.
	signable_class_mapping = {
		'invoice': {
			"class": Invoice,
			"app_label": "invoice_service",
			"serializer": InvoiceSerializer,
			"order_by": "-date_created"
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
			return APIResponse(f"No {target_class} found with ID {object_id}.", status=status.HTTP_404_NOT_FOUND)
		try:
			# Sign the signable object and return a success message.
			signable.sign(request)
		except PermissionError:
			return APIResponse(f"You do not have permission to sign this {target_class} object.", status=status.HTTP_403_FORBIDDEN)
		except ValidationError as ve:
			return APIResponse(f"Unable to sign this {target_class} object: {ve}", status=status.HTTP_400_BAD_REQUEST)
		except Exception as e:
			return APIResponse(f"Internal Error: {e}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
		
		return APIResponse(message="Successful.", status=status.HTTP_200_OK)
	# Return a 404 if the signable class does not exist
	return APIResponse(f"A signable object of type {target_class} was not found.", status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def get_user_signable_view(request, target_class, status_filter="all"):
	'''
		Returns a paginated list of signable objects for the authenticated user.
		Depending on the status_filter, it returns "all", "completed" or "pending" signable objects (for the authenticated user).
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
		try:
			# Get all signable objects.
			signables = signable_class.objects.all().order_by(target.get("order_by"))
			# This user's signables based on the Signatories.
			signables = [obj for obj in signables if any(item in obj.signatories for item in relevant_permissions)]
			# Get signables where roles of the authenticated user has signed
			signed_by_user_role = [obj for obj in signables if any(
				role in (
					(lambda x: map(lambda i: i.role, x))(obj.get_signatures())
				) for role in relevant_permissions
			)]
			# Filter for signable objects that are pending signature from the role of the authenticated user.
			signables = list(filter(lambda s: s.current_pending_signatory in relevant_permissions, signables)) if status_filter == "pending" else signables
			# Filter the signable objects by the ones that have been completed.
			signables = list(filter(lambda s: s.is_completely_signed, signed_by_user_role)) if status_filter == "completed" else signables
			# Filter the signable objects for objects that have been accepted or rejected for the particular role, if the approved param is provided in the request.
			verdict_filter = bool(int(request.GET.get("approved"))) if request.GET.get("approved") else None
			if verdict_filter is not None:
				signables = []
				for signable in signed_by_user_role:
					# Filter the signatures for the particular verdict (True for accepted, False for rejected) AND for the particular user's role
					filtered_signatures = filter(
						lambda i: (i.accepted == verdict_filter) and (i.role in relevant_permissions),
						signable.get_signatures()
					)
					# Add the signable to the signables list.
					signables.append(signable) if signable.id in [item.signable_id for item in filtered_signatures] else None
			# Paginate the queryset.
			paginated = paginator.paginate_queryset(signables, request)
			# Serialize the paginated signables.
			serialized_signables = signable_serializer(paginated, many=True).data
			# Return the paginated response with the serialized signables.
			paginated_data = paginator.get_paginated_response(serialized_signables).data
		except Exception as e:
			return APIResponse(f"Internal Error: {e}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
		# Return the paginated response with the serialized signables.
		return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
	# Return a 404 if the signable class does not exist
	return APIResponse(f"No signable object of type {target_class}.", status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def get_signable_view(request, target_class, status_filter="all"):
	'''
		Returns a paginated list of signable objects for the authenticated user.
		Depending on the status_filter, it returns "all", "completed" or "pending" signable objects (for the authenticated user).
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
		try:
			# Get all signable objects.
			signables = signable_class.objects.all().order_by(target.get("order_by"))
			# Filter for signable objects that are pending signature from the role of the authenticated user.
			signables = list(filter(lambda s: not s.is_completely_signed, signables)) if status_filter == "pending" else signables
			# Filter the signable objects by the ones that have been completed.
			signables = list(filter(lambda s: s.is_completely_signed, signables)) if status_filter == "completed" else signables
			# Filter the signable objects by accepted or rejected, if the approved param is provided in the request.
			verdict_filter = bool(int(request.GET.get("approved"))) if request.GET.get("approved") else None
			signables = list(filter(lambda s: s.is_accepted == verdict_filter, signables)) if verdict_filter else signables
			# Paginate the queryset.
			paginated = paginator.paginate_queryset(signables, request)
			# Serialize the paginated signables.
			serialized_signables = signable_serializer(paginated, many=True).data
			# Return the paginated response with the serialized signables.
			paginated_data = paginator.get_paginated_response(serialized_signables).data
		except Exception as e:
			return APIResponse(f"Internal Error: {e}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
		# Return the paginated response with the serialized signables.
		return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
	# Return a 404 if the signable class does not exist
	return APIResponse(f"No signable object of type {target_class}.", status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def track_signable_view(request, target_class, object_id):
	'''
		Returns a list of all signatures for a specific signable object.
	'''
	# Get the signable class being signed in this request.
	target = get_signable_class(target_class)
	# If the signable class does not exist, return a 404
	if target:
		# Get the Django model and app label for the signable class.
		signable_class = target.get("class")
		# Get the signable object with the provided ID. If it does not exist, return an error message
		try:
			# Using Django's ContentType framework to get the correct content type for the signable class.'
			content_type = ContentType.objects.get_for_model(signable_class)
			# Get all signatures for the signable object.
			signatures = Signature.objects.filter(signable_type=content_type, signable_id=object_id)
			# Paginate the queryset.
			paginated = paginator.paginate_queryset(signatures, request, order_by='-date_signed')
			# Serialize the paginated signatures.
			serialized_signatures = SignatureSerializer(paginated, many=True).data
			# Return the paginated response with the serialized signatures.
			paginated_data = paginator.get_paginated_response(serialized_signatures).data
			return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
		except ObjectDoesNotExist:
			return APIResponse(f"No signatures found for {target_class} {object_id}.", status=status.HTTP_404_NOT_FOUND)
		except Exception as e:
			return APIResponse(f"Internal Error: {e}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
	# Return a 400 if the signable class does not exist
	return APIResponse(f"No signable object of type {target_class}.", status=status.HTTP_400_BAD_REQUEST)