from django.contrib import admin
from unfold.admin import ModelAdmin
from . import models
from .forms import ConversionForm
from django.db.models.fields.json import JSONField
from jsoneditor.forms import JSONEditor
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

def set_app_label(model_admin, app_label="app_settings"):
	"""
	Override the app label of a model and ensure permissions are created for the new label.
	"""
	model_admin._meta.app_label = app_label  # Change the app label
	# Ensure permissions are created for the new app_label
	content_type, created = ContentType.objects.get_or_create(
		model=model_admin._meta.model_name,
		app_label=app_label
	)
	# Define the default Django model permissions 
	default_permissions = ['add', 'change', 'delete', 'view']
	# Create the default Django model permissions for the new app_label and model_name
	for perm in default_permissions:
		codename = f"{perm}_{model_admin._meta.model_name}"
		permission, created = Permission.objects.get_or_create(
			codename=codename,
			content_type=content_type,
			defaults={'name': f'Can {perm} {model_admin._meta.verbose_name}'}
		)
		if created:
			print(f"Created permission: {permission}")

	return model_admin


class ConversionAdmin(ModelAdmin):
	form = ConversionForm
	search_fields = ['name', 'conversion_field', 'conversion_method']
	formfield_overrides = {
		JSONField: {'widget': JSONEditor},
	}

class ProductConfigurationAdmin(ModelAdmin):
	search_fields = ['product_id', 'conversion__name', 'metadata']
	formfield_overrides = {
		JSONField: {'widget': JSONEditor},
	}

class SurchargeAdmin(ModelAdmin):
	# code, description, type, rate
	search_fields = ['code', 'description', 'type', 'rate']
	
class StoreAdmin(ModelAdmin):
	#store_name, store_email, icg_warehouse_name, icg_warehouse_code, byd_cost_center_code, metadata
	search_fields = [
		'store_name',
		'store_email',
		'icg_warehouse_name',
		'icg_warehouse_code',
		'byd_cost_center_code'
	]

class GLAccountAdmin(ModelAdmin):
	# account_code, account_name,
	search_fields = ['account_code', 'account_name']

class GLEntryStateAdmin(ModelAdmin):
	search_fields = [
		'state_name',
		'state_description',
		'gl_account__account_code',
		'gl_account__account_name',
		'transaction_value_field'
	]
	
class ProductCategoryGLEntryAdmin(ModelAdmin):
	search_fields = [
		'product_category_id',
		'product_category_description',
		'credit_states',
		'debit_states'
	]

admin.site.register(
	set_app_label(models.StoreProxy),
	StoreAdmin
)
admin.site.register(
	set_app_label(models.SurchargeProxy),
	SurchargeAdmin
)
admin.site.register(
	set_app_label(models.ConversionProxy),
	ConversionAdmin
)
admin.site.register(
	set_app_label(models.ProductConfigurationProxy),
	ProductConfigurationAdmin
)

# Register models from app_settings as usual
admin.site.register(models.GLAccount, GLAccountAdmin)
admin.site.register(models.GLEntryState, GLEntryStateAdmin)
admin.site.register(models.ProductCategoryGLEntry, ProductCategoryGLEntryAdmin)
