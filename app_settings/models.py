from django.db import models
from egrn_service.models import Store, Conversion, ProductConfiguration, Surcharge


# Create your models here.
class GLAccount(models.Model):
	account_code = models.CharField(max_length=10, unique=True)
	account_name = models.CharField(max_length=255)
	
	def __str__(self):
		return f"{self.account_name} | {self.account_code}"
	
	class Meta:
		verbose_name_plural = '1.3.1 Ledger - Accounts'


class GLEntryState(models.Model):
	state_name = models.CharField(max_length=50)
	state_description = models.CharField(max_length=255)
	gl_account = models.ForeignKey(GLAccount, on_delete=models.CASCADE)
	transaction_value_field = models.CharField(max_length=32, blank=False, null=False)
	
	def __str__(self):
		return f'UPDATE "{self.gl_account.account_name}"'
	
	class Meta:
		verbose_name_plural = '1.3.3 Ledger - States'


class ProductCategoryGLEntry(models.Model):
	ACTIONS = (
		('receipt', 'Receipt'),
		('invoice_approval', 'Invoice Approval'),
	)
	product_category_id = models.CharField(max_length=10)
	product_category_description = models.CharField(max_length=255)
	credit_states = models.ManyToManyField(GLEntryState, related_name='receipt_credit_states')
	debit_states = models.ManyToManyField(GLEntryState, related_name='receipt_debit_states')
	action = models.CharField(max_length=20, choices=ACTIONS)

	def __str__(self):
		return f"On {self.action} of {self.product_category_description}"
	
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=('product_category_id', 'action'), name='unique_product_category_action')
		]
		verbose_name_plural = '1.3.2 Ledger - Entries for Product Categories'
		

"""
	- Proxy models for admin site display purposes to the following egrn models:
		Store, Conversion, ProductConfiguration, Surcharge
"""

class StoreProxy(Store):
	class Meta:
		proxy = True
		verbose_name = '1.1 Store'
		verbose_name_plural = '1.1 Stores'

class ConversionProxy(Conversion):
	class Meta:
		proxy = True
		verbose_name = "1.2.2 Products - Conversion"
		verbose_name_plural = "1.2.2 Products - Conversions"

class ProductConfigurationProxy(ProductConfiguration):
	class Meta:
		proxy = True
		verbose_name = "1.2.1 Products - Configuration"
		verbose_name_plural = "1.2.1 Products - Configurations"

class SurchargeProxy(Surcharge):
	class Meta:
		proxy = True
		verbose_name = "1.4 Surcharge"
		verbose_name_plural = "1.4 Surcharges"