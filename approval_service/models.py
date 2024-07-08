from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from abc import ABC, ABCMeta, abstractmethod
import hashlib
from dataclasses import dataclass

user = get_user_model()

class AbstractModelMeta(ABCMeta, type(models.Model)):
	'''
		A metaclass for the AbstractModel class.
		We need to inherit from this class to use abstract methods in a Django abstract model.
	'''
	pass

class Signable(models.Model, metaclass=AbstractModelMeta):
	'''
		A signable object is an object that can be signed by an authorized user.
	'''
	# Define the digest field to store the hash value
	digest = models.CharField(max_length=64, blank=True, null=True)
	# Define the signatories from the workflow.
	signatories = models.JSONField(blank=False, null=False, default=dict)
	
	@property
	def is_valid(self):
		# Property that states whether the hash of the object is valid
		return self.verified
	
	class Meta:
		abstract = True
		permissions = [
			("can_sign_signable", "Can sign a signable object."),
		]
	
	@abstractmethod
	def set_identity(self):
		"""
			Method to be implemented by child classes.
			This method should return the data that needs to be hashed.
		"""
		pass
	
	@abstractmethod
	def seal_class(self) -> bool:
		"""
			Method to be implemented by child classes.
			This method should trigger the sealing process (i.e. update the digest field)
		"""
		pass
	
	@abstractmethod
	def set_signatories(self):
		"""
			Method to be implemented by child classes.
			This method gets the workflow for the signable object.
		"""
		pass
	
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# Re-verify the hash before initializing the model instance
		self.verify_hash() if self.digest else None
	
	def save(self, *args, **kwargs):
		# This model can only be created, not modified
		if self.pk:
			raise Exception("Signable models can not be modified")
		super().save(*args, **kwargs)
	
	def calculate_digest(self, ):
		identity_data = self.identity_data
		# Hash the identity data using SHA-256 (you can use any hash algorithm)
		hashed_string = hashlib.sha256(identity_data.encode()).hexdigest()
		# Update the digest field with the calculated hash
		return hashed_string
	
	def update_digest(self, ) -> bool:
		try:
			self.digest = self.calculate_digest()
			super().save(update_fields=['signatories', 'digest'])
		except Exception as e:
			raise e
		# Return True if the hash was updated successfully
		return True
	
	def verify_hash(self, ):
		# Call the set_identity method to populate the self.digest
		self.set_identity()
		# Recalculate the hash and check if the recalculated hash matches the stored hash, set the value of the verified property
		self.verified = self.digest == self.calculate_digest()
		
	def sign(self, request: object) -> bool:
		signatories = self.signatories
		
		print(signatories)


class Signature(models.Model):
	"""
		This model is used to store the signatures of a signable object.
	"""
	# VERDICT_CHOICES = (
	# 	(1, 'Accepted'),
    #   (-1, 'Rejected'),
    #   (0, 'Review'),
	# )
	# Define the signer field to store the user who signed the signable object
	signer = models.ForeignKey(user, on_delete=models.CASCADE, related_name='signatures')
	# Define the digest field to store the signature hash
	signature = models.CharField(max_length=255, blank=False, null=False)
	# Define a field to show the descision of the signer regarding the signable object
	accepted = models.BooleanField(default=False, blank=False, null=False)
	# Compulsory comment from the signer regarding their acceptance status
	comment = models.TextField(blank=False, null=False)
	# The date and time when the signature was signed
	date_signed = models.DateTimeField(auto_now_add=True)
	# Generic relation to the signable object
	signable_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
	signable_id = models.PositiveIntegerField()
	signable = GenericForeignKey("signable_type", "signable_id")
	# A metadata field to store other data about the signature
	metadata = models.JSONField(default=dict)


class Keystore(models.Model):
	'''
		A class to store the public keys of users.
	'''
	user = models.ForeignKey(user, on_delete=models.CASCADE, related_name='public_keys')
	public_key = models.CharField(max_length=255, blank=False, null=False)
	created_at = models.DateTimeField(auto_now_add=True)
	active = models.BooleanField(default=True)

@dataclass
class Workflow(ABC):
	'''
		A workflow is a set of rules that define the approval process flow for a signable object.
	'''
	# A colloquial name for the workflow
	name: str
	# A signable object that the workflow applies to
	signable: object
	# If the workflow is complete
	complete: bool = False
	signatory_permissions: tuple = ()
	
	@abstractmethod
	def get_signatories(self) -> tuple:
		'''
			Returns a tuple of the roles that the signatories must have to sign the signable object, in order of precedence.
		'''
		pass
	
	def is_complete(self) -> bool:
		return self.complete
