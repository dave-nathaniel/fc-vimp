from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import CustomUser, VendorProfile, TempUser

class CustomUserAdmin(ModelAdmin):
	# Search fields
	search_fields = ['username', 'email', 'first_name', 'last_name']
	exclude_from_view = ("secret", "password",)
	
	def get_fields(self, request, obj=None):
		"""
			Show 'secret' field only when creating a new user.
		"""
		fields = super().get_fields(request, obj)
		return [field for field in fields if field not in self.exclude_from_view] if obj else fields

	def get_readonly_fields(self, request, obj=None):
		"""
			Ensure 'secret' remains read-only even if accessed.
		"""
		if obj:  # If editing, make 'secret' readonly
			return super().get_readonly_fields(request, obj) + self.exclude_from_view
		return super().get_readonly_fields(request, obj)


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