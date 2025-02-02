from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import CustomUser, VendorProfile, TempUser

class CustomUserAdmin(ModelAdmin):
	# Search fields
	search_fields = ['username', 'email', 'first_name', 'last_name']

class VendorProfileAdmin(ModelAdmin):
	# Search fields
	search_fields = [
		'phone',
		'byd_internal_id',
		'user__email',
		'user__username',
		'user__first_name',
		'user__last_name',
	]
class TempUserAdmin(ModelAdmin):
	# Search fields
	search_fields = ['identifier', 'id_type', 'byd_metadata__BusinessPartner__InternalID', 'byd_metadata__BusinessPartner__BusinessPartnerFormattedName']

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(VendorProfile, VendorProfileAdmin)
admin.site.register(TempUser, TempUserAdmin)