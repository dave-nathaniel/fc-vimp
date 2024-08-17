from rest_framework import serializers
from .models import Signature

class SignatureSerializer(serializers.ModelSerializer):
	signer = serializers.SerializerMethodField()
	role = serializers.CharField()
	approved = serializers.BooleanField(source='accepted')
	predecessor = serializers.SerializerMethodField()
	
	def get_signer(self, obj):
		return {
			"name": obj.signer.first_name + " " + obj.signer.last_name,
			"email": obj.signer.email,
			"username": obj.signer.username,
		}
	
	def get_predecessor(self, obj):
		if obj.predecessor:
			return SignatureSerializer(obj.predecessor).data
		return None
	
	class Meta:
		model = Signature
		fields = ['id', 'signer', 'role', 'approved', 'comment', 'date_signed', 'predecessor']