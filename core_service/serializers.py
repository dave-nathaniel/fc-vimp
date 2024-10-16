# Vendor Profile serializer
import logging
from rest_framework import serializers
from core_service.models import VendorProfile
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import validate_password
from django_q.tasks import async_task

CustomUser = get_user_model()


class RelatedObjectDoesNotExist:
	pass


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
	
	def get_user_data(self, user):
		user_data = {
			'id': user.id,
			'username': user.username,
			'email': user.email
		}
		# Try to get the vendor_profile related to the user. If the user does not have a vendor_profile,
		# then they are probably not a vendor; return the first_name and last_name
		try:
			user_data['vendor_settings'] = user.vendor_profile.vendor_settings
			user_data['vendor_name'] = user.first_name
		except ObjectDoesNotExist:
			user_data['first_name'] = user.first_name
			user_data['last_name'] = user.last_name
		
		return user_data
	
	def to_representation(self, instance):
		# Include user information in the response
		data = super().to_representation(instance)
		return self.get_user_data(instance)
	
	@classmethod
	def get_token(cls, user):
		token = super().get_token(user)
		# Add custom claims to the token
		token['user'] = cls.get_user_data(cls, user)
		return token
	
	def validate(self, attrs):
		data = super().validate(attrs)
		user = self.user or self.context['request'].user
		# Include user information in the response
		data['user'] = self.get_user_data(user)
		return data
	
	class Meta:
		model = CustomUser
		fields = '__all__'


class VendorProfileSerializer(serializers.ModelSerializer):
	def create(self, validated_data):
		vendor_profile = VendorProfile.objects.create(validated_data)
		return vendor_profile
	
	def to_representation(self, instance):
		data = super().to_representation(instance)
		vendor = CustomTokenObtainPairSerializer(instance.user).data
		vendor.update(data)
		# vendor.pop('byd_metadata')
		return vendor
		
	class Meta:
		model = VendorProfile
		exclude = ['id', 'user']
		read_only_fields = ['byd_metadata', 'byd_internal_id', 'user', 'created_on']


class PasswordResetRequestSerializer(serializers.Serializer):
	email = serializers.EmailField()

	def validate_email(self, value):
		try:
			self.user = CustomUser.objects.get(email=value)
		except CustomUser.DoesNotExist:
			raise serializers.ValidationError("Email not found.")
		return value

	def save(self, **kwargs):
		token = default_token_generator.make_token(self.user)
		# Here you should send the token to the user's email or phone.
		async_task('vimp.tasks.send_reset_link_to_user', {
			"token": token,
			"user": self.user,
		})
		return token


class PasswordResetSerializer(serializers.Serializer):
	token = serializers.CharField()
	email = serializers.EmailField()
	new_password = serializers.CharField(write_only=True)

	def validate(self, attrs):
		self.user = CustomUser.objects.get(email=attrs["email"])
		if not default_token_generator.check_token(self.user, attrs["token"]):
			raise serializers.ValidationError("Invalid or expired token.")
		return attrs

	def save(self, **kwargs):
		self.user.set_password(self.validated_data["new_password"])
		self.user.save()


class PasswordChangeSerializer(serializers.Serializer):
	old_password = serializers.CharField(write_only=True)
	new_password = serializers.CharField(write_only=True)

	def validate_old_password(self, value):
		user = self.context['request'].user
		if not user.check_password(value):
			raise serializers.ValidationError("Old password is incorrect.")
		return value

	def validate_new_password(self, value):
		validate_password(value)
		return value

	def save(self, **kwargs):
		user = self.context['request'].user
		user.set_password(self.validated_data['new_password'])
		user.save()
