# Import necessary modules and classes
import sys
import logging
import hashlib
from django.db import IntegrityError
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import permission_classes, api_view, authentication_classes
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from overrides.rest_framework import APIResponse
from byd_service.rest import RESTServices
from core_service.models import TempUser, VendorProfile
from core_service.serializers import VendorProfileSerializer
from egrn_service.models import PurchaseOrder, Surcharge
from egrn_service.serializers import PurchaseOrderSerializer
from invoice_service.serializers import SurchargeSerializer

from overrides.authenticate import CombinedAuthentication

# Initialize REST services
byd_rest_services = RESTServices()
# Get the user model
User = get_user_model()


# View for handling new user creation and setup
class NewUserView(APIView):
	permission_classes = []
	def post(self, request, *args, **kwargs):
		# Get the action from URL parameters
		action = kwargs.get("action")
		
		try:
			if action == 'new':
				# Extract necessary data from request
				vendor_id = request.data.get("id")
				id_type = request.data.get("type")
				
				# Fetch vendor details from external service
				get_vendor = byd_rest_services.get_vendor_by_id(vendor_id, id_type) if vendor_id and id_type else None
				
				if get_vendor:
					# Prepare data for temporary user creation
					new_values = {"identifier": vendor_id, "id_type": id_type, "byd_metadata": get_vendor}
					
					try:
						# Create or update temporary user
						obj, created = TempUser.objects.update_or_create(identifier=vendor_id, defaults=new_values)
						if created:
							return APIResponse(
								f'Verification process initiated for vendor \'{vendor_id}\'; please check your {id_type} for further instructions to verify your identity and complete your account setup.',
								status.HTTP_201_CREATED)
						else:
							return APIResponse(f'Setup already initiated for vendor with {id_type} \'{vendor_id}\'.',
											   status.HTTP_200_OK)
					
					except IntegrityError as e:
						return APIResponse(
							f'Vendor with {id_type} \'{vendor_id}\' has already been setup on the system.',
							status.HTTP_400_BAD_REQUEST)
				else:
					return APIResponse(f'No vendor found with {id_type} \'{vendor_id}\'', status.HTTP_404_NOT_FOUND)
			
			if action == 'verifysetup':
				# Extract data from request
				identifier = request.data.get("identity_hash")
				token = request.data.get("token")
				
				# Fetch temporary user with provided token
				temp_user = TempUser.objects.filter(token=token).first()
				
				if temp_user:
					# Concatenate data to form hash for verification
					hash_concat = f'{temp_user.identifier}{temp_user.id_type}{temp_user.byd_metadata["BusinessPartner"]["BusinessPartnerFormattedName"]}{temp_user.token}'
					id_hash = hashlib.sha256()
					id_hash.update(str.encode(hash_concat))
					identity_hash = id_hash.hexdigest()
					
					# Verify and update temporary user
					if not temp_user.verified and identifier == identity_hash:
						temp_user.verified = True
						temp_user.save()
					
					return APIResponse("Verification successful", status.HTTP_200_OK, data={"token": temp_user.token})
				else:
					return APIResponse(f'Invalid parameters.', status.HTTP_400_BAD_REQUEST)
			
			if action == 'createpassword':
				# Extract data from request
				token = request.data.get("token")
				password = request.data.get("new_password")
				# Fetch temporary user with provided token
				temp_user = TempUser.objects.filter(token=token).first()
				if temp_user and temp_user.verified and not temp_user.account_created:
					# Extract user details from metadata
					business_name = temp_user.byd_metadata['BusinessPartner']['BusinessPartnerFormattedName'].strip()
					username = temp_user.byd_metadata['BusinessPartner']['InternalID'].strip()
					internal_id = username
					email = temp_user.identifier if temp_user.id_type == 'email' else temp_user.byd_metadata['Email'][
						'URI']
					phone = temp_user.byd_metadata['ConventionalPhone'].get('NormalisedNumberDescription', None)
					phone = phone[-10:] if phone else phone
					# Update temporary user and create new user
					temp_user.account_created = True
					temp_user.save()
					
					new_user = User.objects.create_user(username=username, email=email, password=password,
														first_name=business_name)
					# We get or create because services like GRN might have already created a profile and
					# attached models to it before the vendor does their onboarding.
					vendor, created = VendorProfile.objects.get_or_create(byd_internal_id=internal_id)
					if created:
						# Full BYD metadata
						vendor.byd_metadata = temp_user.byd_metadata
					# Attach the newly created user
					vendor.user = new_user
					# Phone from Byd
					vendor.phone = phone
					# Save the model
					vendor.save()
					
					return APIResponse(f'Vendor \'{username}\' created.', status.HTTP_201_CREATED)
				else:
					return APIResponse(f'Illegal operation.', status.HTTP_400_BAD_REQUEST)
			
			return APIResponse("Unknown operation.", status.HTTP_400_BAD_REQUEST)
		
		except Exception as e:
			logging.error(e)
			return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)


class VendorProfileView(APIView):
	"""
	Retrieve, update or delete a vendor profile instance.
	"""
	serializer_class = VendorProfileSerializer
	permission_classes = (IsAuthenticated,)
	
	def get(self, request, format=None):
		try:
			vendor_profile = VendorProfile.objects.get(user=request.user)
		except ObjectDoesNotExist:
			return APIResponse(f"A Vendor Profile was not found for this user.", status=status.HTTP_404_NOT_FOUND)
		
		vendor_profile_serializer = VendorProfileSerializer(vendor_profile)
		return APIResponse("Vendor Profile Retrieved", status.HTTP_200_OK, data=vendor_profile_serializer.data)

	def put(self, request, format=None):
		"""
		Update the Vendor's Profile.
		"""
		try:
			vendor_profile = VendorProfile.objects.get(user=request.user)
		except ObjectDoesNotExist:
			return APIResponse(f"No profile found for this vendor.", status=status.HTTP_404_NOT_FOUND)
		
		update = {**request.data}
		vendor_profile_serializer = VendorProfileSerializer(vendor_profile, data=update, partial=True)
		
		if vendor_profile_serializer.is_valid():
			vendor_profile.save(data={**vendor_profile_serializer.validated_data})
			return APIResponse("Vendor Profile Updated", status.HTTP_200_OK, data=vendor_profile_serializer.data)
		else:
			return APIResponse(vendor_profile_serializer.errors, status.HTTP_400_BAD_REQUEST)

	
# View for retrieving purchase orders
@api_view(['GET'])
@permission_classes((IsAuthenticated,))
def get_vendors_orders(request, po_id=None):
	"""
	Retrieve the Vendor's Purchase Orders that have been delivered.
	"""
	try:
		if po_id:
			orders = PurchaseOrder.objects.get(po_id=po_id, vendor=request.user.vendor_profile)
			serializer = PurchaseOrderSerializer(orders)
		else:
			orders = PurchaseOrder.objects.filter(vendor=request.user.vendor_profile)
			serializer = PurchaseOrderSerializer(orders, many=True)
		# If there are no orders, return an empty list
		data = [] if not serializer.data else serializer.data
		return APIResponse("Purchase Orders Retrieved", status.HTTP_200_OK, data=data)
	
	except ObjectDoesNotExist:
		return APIResponse(f"No delivered purchase orders found.", status.HTTP_404_NOT_FOUND)
	except Exception as e:
		return APIResponse(f"Internal Error: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@authentication_classes([CombinedAuthentication,])
# get surcharges
def get_surcharges(request):
	# return all surcharges from the models.Surcharge model
	surcharges = Surcharge.objects.all()
	serializer = SurchargeSerializer(surcharges, many=True)
	return APIResponse("Surcharges Retrieved", status.HTTP_200_OK, data=serializer.data)