from django.contrib import admin, messages
from unfold.admin import ModelAdmin
from byd_service.rest import RESTServices
from .models import CustomUser, VendorProfile, TempUser

byd_rest_services = RESTServices()

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
	actions = ['resync_profiles']

	def resync_profiles(self, request, queryset):
		success = 0
		errors = []
		for vendor in queryset:
			contact = vendor.user.username if vendor.user else None
			if not contact:
				errors.append(f"Vendor {vendor.byd_internal_id} has no user email.")
				continue
			try:
				vendor_data = byd_rest_services.get_vendor_by_id(contact, 'internal_id')
				if not vendor_data:
					errors.append(f"No ByD data found for {contact}.")
					continue
				vendor.byd_metadata = vendor_data
				phone = vendor_data.get('ConventionalPhone', {}).get('NormalisedNumberDescription')
				if phone:
					vendor.phone = phone[-10:] if len(phone) > 10 else phone
				user = vendor.user
				if user:
					updated_user = False
					email = vendor_data.get('EMail', {}).get('URI')
					if email and user.email != email:
						user.email = email
						updated_user = True
					business_partner = vendor_data.get('BusinessPartner', {})
					first_name = business_partner.get('FirstName')
					last_name = business_partner.get('LastName')
					if not first_name or not last_name:
						formatted_name = business_partner.get('BusinessPartnerFormattedName', '').strip()
						if formatted_name:
							parts = formatted_name.split()
							if not first_name and parts:
								first_name = parts[0]
							if not last_name and len(parts) > 1:
								last_name = ' '.join(parts[1:])
					if first_name and user.first_name != first_name:
						user.first_name = first_name
						updated_user = True
					if last_name and user.last_name != last_name:
						user.last_name = last_name
						updated_user = True
					if updated_user:
						user.save()
				vendor.save()
				success += 1
			except Exception as exc:
				errors.append(f"{contact}: {exc}")

		if success:
			self.message_user(request, f"{success} vendor profile(s) resynced.", level=messages.SUCCESS)
		for error in errors:
			self.message_user(request, error, level=messages.ERROR)

	resync_profiles.short_description = "Resync selected vendor profiles from ByD"
class TempUserAdmin(ModelAdmin):
	# Search fields
	search_fields = ['identifier', 'id_type', 'byd_metadata__BusinessPartner__InternalID', 'byd_metadata__BusinessPartner__BusinessPartnerFormattedName']

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(VendorProfile, VendorProfileAdmin)
admin.site.register(TempUser, TempUserAdmin)