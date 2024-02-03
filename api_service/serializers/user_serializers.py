from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

CustomUser = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
	@classmethod
	def get_token(cls, user):
		token = super().get_token(user)
		# Add custom claims to the token, if needed
		return token

	def validate(self, attrs):
		data = super().validate(attrs)
		user = self.user or self.context['request'].user
		# Include user information in the response
		data['user'] = {
			'id': user.id,
			'username': user.username,
			'email': user.email,
			'firstname': user.first_name,
			'lastname': user.last_name,
		}

		return data