# Vendor Profile serializer
from rest_framework import serializers
from core_service.models import VendorProfile
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.forms.models import model_to_dict

CustomUser = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
	@classmethod
	def get_token(cls, user):
		token = super().get_token(user)
		# Add custom claims to the token, if needed
		return token
	
	# noinspection PyTypeChecker
	def validate(self, attrs):
		data = super().validate(attrs)
		user = self.user or self.context['request'].user
		# Include user information in the response
		data['user'] = {
			'id': user.id,
			'username': user.username,
			'email': user.email,
			'vendor_name': user.first_name,
			'vendor_settings': user.vendor_profile.vendor_settings
		}

		return data
	
	def to_representation(self, instance):
		user = instance
		return {
			'username': user.username,
			'email': user.email,
			'vendor_name': user.first_name,
		}
	
	class Meta:
		model = CustomUser
		fields = '__all__'


class VendorProfileSerializer(serializers.ModelSerializer):
	user = CustomTokenObtainPairSerializer(read_only=True)
	class Meta:
		model = VendorProfile
		exclude = ['id']
		read_only_fields = ['byd_metadata', 'byd_internal_id', 'user', 'created_on']
	
	def create(self, validated_data):
		vendor_profile = VendorProfile.objects.create(validated_data)
		return vendor_profile
