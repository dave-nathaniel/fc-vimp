import logging
import hashlib
from pprint import pprint
from rest_framework import status
from django.db import IntegrityError
from rest_framework.views import APIView
from byd_service.rest import RESTServices
from django.contrib.auth import get_user_model
from .overrides.rest_framework import APIResponse
from core_service.models import TempUser, VendorProfile
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers.user_serializers import CustomTokenObtainPairSerializer

byd_rest_services = RESTServices()

User = get_user_model()


class NewUserView(APIView):

	def post(self, request, *args, **kwargs):

		action = kwargs.get("action")

		try:
			if action == 'new':
				vendor_id = request.data.get("id")
				id_type = request.data.get("type")

				get_vendor = byd_rest_services.get_vendor_by_id(vendor_id, id_type) if vendor_id and id_type else None

				if get_vendor:
					new_values = {"identifier": vendor_id, "id_type": id_type, "byd_metadata":get_vendor}

					try:
						obj, created = TempUser.objects.update_or_create(identifier=vendor_id, defaults=new_values)
						if created:
							# obj.update(**new_values)
							return APIResponse(f'Verification process initiated for vendor \'{vendor_id}\'; please check your {id_type} for further instructions to verify your identity and complete your account setup.', status.HTTP_201_CREATED)
						else:
							print("not created")
							return APIResponse(f'You have a pending verification, we have resent instructions to your {id_type} \'{vendor_id}\'.', status.HTTP_200_OK)

					except IntegrityError as e:
						return APIResponse(f'Vendor with {id_type} \'{vendor_id}\' has already been setup on the system.', status.HTTP_400_BAD_REQUEST)
				
				return APIResponse(f'No vendor found with {id_type} \'{vendor_id}\'', status.HTTP_404_NOT_FOUND)

			if action == 'verifysetup':
				identifier = request.data.get("identity_hash")
				token = request.data.get("token")

				temp_user = TempUser.objects.filter(token=token).first()

				if temp_user:
					hash_concat = f'{temp_user.identifier}{temp_user.id_type}{temp_user.byd_metadata["BusinessPartner"]["BusinessPartnerFormattedName"]}{temp_user.token}'
					id_hash = hashlib.sha256()
					id_hash.update(str.encode(hash_concat))
					identity_hash = id_hash.hexdigest()

					if not temp_user.verified and identifier == identity_hash:
						temp_user.verified = True
						temp_user.save()

					return APIResponse("Verification successful", status.HTTP_200_OK, data={"token": temp_user.token})

			if action == 'createpassword':
				token = request.data.get("token")
				password = request.data.get("new_password")

				temp_user = TempUser.objects.filter(token=token).first()

				if temp_user and temp_user.verified and not temp_user.account_created:
					username = temp_user.byd_metadata['BusinessPartner']['InternalID'].strip()
					email = temp_user.identifier if temp_user.id_type == 'email' else temp_user.byd_metadata['Email']['URI']
					phone = temp_user.byd_metadata['ConventionalPhone'].get('NormalisedNumberDescription', None)
					phone = phone[:-10] if phone else phone
					internal_id = username

					temp_user.account_created = True
					temp_user.save()

					new_user = User.objects.create_user(username=username, email=email, password=password)
					new_user.first_name = temp_user.byd_metadata['BusinessPartner']['BusinessPartnerFormattedName'].strip()

					vendor = VendorProfile.objects.create(user=new_user, phone=phone, byd_internal_id=username, byd_metadata=temp_user.byd_metadata)
					vendor.save()

					return APIResponse(f'Vendor \'{username}\' created.', status.HTTP_201_CREATED)

				return APIResponse(f'Illegal operation.', status.HTTP_401_UNAUTHORIZED)

			return APIResponse("Malformed Request.", status.HTTP_400_BAD_REQUEST)

		except Exception as e:
			logging.error(e)
			raise e
			return APIResponse("Internal Error.", status.HTTP_500_INTERNAL_SERVER_ERROR)
			
class CustomTokenObtainPairView(TokenObtainPairView):

	serializer_class = CustomTokenObtainPairSerializer

	def post(self, request, *args, **kwargs):
		response = super().post(request, *args, **kwargs)
		return APIResponse('Authenticated', status.HTTP_200_OK, data=response.data)