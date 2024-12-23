from django.db import models

# Create your models here.
class GLAccount(models.Model):
	account_code = models.CharField(max_length=10, unique=True)
	account_name = models.CharField(max_length=255)
	
	def __str__(self):
		return f"{self.account_name} | {self.account_code}"


class GLEntryState(models.Model):
	state_name = models.CharField(max_length=50)
	state_description = models.CharField(max_length=255)
	gl_account = models.ForeignKey(GLAccount, on_delete=models.CASCADE)
	transaction_value_field = models.CharField(max_length=32, blank=False, null=False)
	
	def __str__(self):
		return f'UPDATE "{self.gl_account.account_name}"'


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
