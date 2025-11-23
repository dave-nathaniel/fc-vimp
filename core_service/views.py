# API view to update Vendor Profile
import pyotp
from django.contrib.auth import authenticate, get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from overrides.rest_framework import APIResponse
from .serializers import CustomTokenObtainPairSerializer, PasswordResetRequestSerializer, PasswordResetSerializer, PasswordChangeSerializer
from django_q.tasks import async_task


Users = get_user_model()

format_serializer_errors = lambda e: "; ".join([f"{key.title()} Error: {''.join([v.title() for v in values])}" for key, values in e.errors.items()])

def generate_token_for_user(user):
	# Get the token data
	token = CustomTokenObtainPairSerializer.get_token(user)
	# Generate a dictionary with token and user details
	return {
		'refresh': str(token),
		'access': str(token.access_token),
		'user': CustomTokenObtainPairSerializer().get_user_data(user)
	}

@api_view(['POST'])
@permission_classes([])
def login_user(request):
	"""
		Authenticate a user using their username and password and generate an OTP code.
	"""
	username = request.data.get('username')
	password = request.data.get('password')
	# Authenticate the user using their username and password.
	user = authenticate(request, username=username, password=password)
	# If the user is valid, generate an OTP
	if user is not None:
		# Generate a secret key for the user.
		users_secret = pyotp.random_base32()
		# Generate a TOTP object using the secret key.
		otp = pyotp.TOTP(users_secret, interval=600).now()
		# Encrypt the secret with the generated OTP and save to the user's profile.
		user.secret = user.make_secret(key=otp, secret=users_secret)
		user.save()
		# Send the OTP to the user asynchronously.'
		async_task('vimp.tasks.send_otp_to_user', {
			"otp": otp,
			"user": user,
			"request": {
				"user_agent": request.META.get('HTTP_USER_AGENT'),
				"ip": request.META.get('REMOTE_ADDR'),
				"os": request.META.get('OS')
			}
		},
		q_options={
			'task_name': f'Send-OTP-To-{username}',
		})
		return APIResponse(f"An OTP has been sent to the contacts associated with your account. Please provide OTP to continue.", status=status.HTTP_200_OK)
	# If the user is not valid, return an error message.
	return APIResponse("Invalid credentials", status=status.HTTP_401_UNAUTHORIZED)


@api_view(['POST'])
@permission_classes([])
def verify_otp(request):
	"""
		Verify the OTP code provided by the user.
	"""
	otp_code = request.data.get('otp')
	username = request.data.get('username')
	# Get the user from the database using their username.
	user = Users.objects.filter(username=username).first()
	# Verify the OTP code using the user's secret key.
	if user is not None:
		try:
			# Decrypt the secret key using the provided OTP code.
			users_secret = user.get_secret(key=otp_code)
			# Verify the OTP code using the decrypted secret key.
			otp_obj = pyotp.TOTP(users_secret, interval=600)
			# If the OTP code is valid:
			if otp_obj.verify(otp_code):
				# Remove the secret key from the user's profile
				user.secret = None
				user.save()
				# Generate a JWT token
				token = generate_token_for_user(user)
				# Return the JWT token
				return APIResponse("OTP verified", data=token, status=status.HTTP_200_OK)
		except ValueError:
			return APIResponse("The OTP provided is either invalid or expired.", status=status.HTTP_400_BAD_REQUEST)
		except Exception:
			return APIResponse("An error occurred.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
	# If the user is not found, return an error message.
	return APIResponse("The OTP provided is either invalid or expired.", status=status.HTTP_401_UNAUTHORIZED)


class PasswordResetRequestView(APIView):
	permission_classes = []

	def post(self, request):
		serializer = PasswordResetRequestSerializer(data=request.data)
		if serializer.is_valid():
			token = serializer.save()
			return APIResponse("Password reset link sent.", status=status.HTTP_200_OK)
		return APIResponse(format_serializer_errors(serializer), status=status.HTTP_400_BAD_REQUEST)


class PasswordResetView(APIView):
	permission_classes = []

	def post(self, request):
		serializer = PasswordResetSerializer(data=request.data)
		if serializer.is_valid():
			serializer.save()
			return APIResponse("Password has been reset.", status=status.HTTP_200_OK)
		return APIResponse(format_serializer_errors(serializer), status=status.HTTP_400_BAD_REQUEST)


class PasswordChangeView(APIView):
	permission_classes = [IsAuthenticated]

	def post(self, request):
		serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
		if serializer.is_valid():
			serializer.save()
			return APIResponse("Password has been changed.", status=status.HTTP_200_OK)
		return APIResponse(format_serializer_errors(serializer), status=status.HTTP_400_BAD_REQUEST)