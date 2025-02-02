from django.contrib import admin
from .models import Signature
from unfold.admin import ModelAdmin


class SignatureAdmin(ModelAdmin):
	# Search fields
	search_fields = [
		'signer__username',
		'signer__first_name',
		'signer__email',
		'comment',
		'metadata__acting_as'
	]

admin.site.register(Signature, SignatureAdmin)