from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from abc import ABC, ABCMeta, abstractmethod
import hashlib
from dataclasses import dataclass
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.signals import post_delete
from django.dispatch import receiver


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
		For the most part, objects of class can only be created but not modified, modifications will cause the hash
		digest to be invalid.
	'''
	# Define the digest field to store the hash value
	digest = models.CharField(max_length=64, blank=True, null=True)
	# Define the signatories from the workflow.
	signatories = models.JSONField(blank=False, null=False, default=dict)
	# Current pending signatory for signing the signable object.
	current_pending_signatory = models.CharField(max_length=150, blank=True, null=True)
	
	@property
	def is_valid(self):
		# Property that states whether the hash of the object is valid
		return self.verified
	
	@property
	def is_completely_signed(self):
		'''
			Property that states whether the signable object is completely signed by all its signatories.
		'''
		return len(self.get_signatures()) == len(self.signatories)
	
	@property
	def is_rejected(self):
		'''
			Property that states whether the signable object has been rejected by any of its signatories.
		'''
		last_signature = self.get_last_signature()
		if last_signature:
			return last_signature.accepted is False
		return False
	
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
	
	def calculate_digest(self, ):
		identity_data = self.identity_data
		# Hash the identity data using SHA-256 (you can use any hash algorithm)
		hashed_string = hashlib.sha256(identity_data.encode()).hexdigest()
		# Update the digest field with the calculated hash
		return hashed_string
	
	def update_digest(self, ) -> bool:
		try:
			self.digest = self.calculate_digest()
			super().save(update_fields=['signatories', 'current_pending_signatory', 'digest'])
		except Exception as e:
			raise e
		# Return True if the hash was updated successfully
		return True
	
	def verify_hash(self, ):
		# Call the set_identity method to populate the self.digest
		self.set_identity()
		# Recalculate the hash and check if the recalculated hash matches the stored hash, set the value of the verified property
		self.verified = self.digest == self.calculate_digest()
	
	def get_signatures(self):
		"""
			Method to get all the signatures for the signable object.
			This method uses Django's ContentType and Signature models to retrieve the signatures.
		"""
		content_type = ContentType.objects.get_for_model(self)
		signatures = Signature.objects.filter(signable_type=content_type, signable_id=self.id).order_by("-date_signed")
		return signatures
	
	def get_current_pending_signatory(self):
		"""
			Method to get the current pending signatory for the signable object.
			This method uses the workflow and the signatories to determine the current pending signatory.
		"""
		signatories = self.signatories
		# The number of signatures made
		number_of_signatures_made = len(self.get_signatures()) or 0
		# Check if there are any pending signatories
		if not signatories:
			return None
		# The number of signatures made can be passed an index to the list of signatories to get the current pending signatory
		return signatories[number_of_signatures_made] if number_of_signatures_made < len(signatories) else None
	
	def get_last_signature(self):
		"""
			Method to get the last signature for the signable object.
			This method uses Django's ContentType and Signature models to retrieve the last signature.
		"""
		content_type = ContentType.objects.get_for_model(self)
		signature = Signature.objects.filter(signable_type=content_type, signable_id=self.id).last()
		return signature
	
	def reset_current_pending_signatory(self, ) -> bool:
		"""
			Method to reset the current pending signatory for the signable object.
			This method clears the current_pending_signatory field.
		"""
		self.current_pending_signatory = self.get_current_pending_signatory()
		super().save(update_fields=['current_pending_signatory'])
	
	def sign(self, request: object) -> bool:
		"""
			Method to sign the signable object.
			Before recording a signature, this method checks:
				- That this object has not been rejected
				- That the object has not been completely signed yet
				- If the user has the necessary permissions to sign the object, and then creates a new signature.
		"""
		# Check that this object has not been rejected
		if self.is_rejected:
			raise ValidationError("This object has been rejected.")
		# Check that this object has not been completely signed yet
		if self.is_completely_signed:
			raise ValidationError("This object has been completely signed.")
		# Check that the user attempting to sign is the (has the role) current pending signatory
		required_permission = f"{self._meta.app_label}.{self.get_current_pending_signatory()}"
		if not request.user.has_perm(required_permission):
			raise PermissionDenied("You do not have permission to sign this object.")
		
		try:
			# Get the content type of the signable object
			content_type = ContentType.objects.get_for_model(self)
			# Create a new signature object and populate its fields
			new_signature = Signature()
			# Fields of the signature class
			new_signature.signer = request.user
			new_signature.signature = request.headers.get('Authorization').split(' ')[1] # TODO: Make the signature cryptographically reference the digest of the signable object
			new_signature.accepted = request.data.get('approved')
			new_signature.comment = request.data.get('comment')
			new_signature.signable_type = content_type
			new_signature.signable_id = self.id
			new_signature.metadata = {
				"acting_as": self.current_pending_signatory
			}
			# Save the new signature object to the database and update the signable object accordingly
			new_signature.save()
			# Update the current pending signatory of the signable
			self.current_pending_signatory = self.get_current_pending_signatory()
			# Use the super class to effect the update because we placed restrictions on the "save"
			# method of this class to prevent modifications to the signable object.
			super().save(update_fields=['current_pending_signatory'])
		except Exception as e:
			raise Exception("Unable to sign the object: ", str(e))
		# If no exceptions were raised, the signature was successfully created and saved
		return True
	
	def save(self, *args, **kwargs):
		# This model can only be created, not modified
		if self.pk:
			raise Exception("Signable models can not be modified")
		super().save(*args, **kwargs)
	
	
class Signature(models.Model):
	"""
		This model is used to store the signatures of a signable object.
	"""
	# Define the signer field to store the user who signed the signable object
	signer = models.ForeignKey(user, on_delete=models.CASCADE, related_name='signatures')
	# Define the digest field to store the signature hash
	signature = models.TextField(blank=False, null=False)
	# Define a field to show the decision of the signer regarding the signable object
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
	# Define a predecessor field to store reference to the previous signature
	predecessor = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='successors')
	
	@property
	def role(self) -> str:
		return self.metadata.get('acting_as', '')
	
	def validate_signature(self, ) -> bool:
		# check_token_valid = AdfsBaseBackend().validate_access_token(jwt_token)
		pass
		
	def save(self, *args, **kwargs):
		if self.pk:
			raise Exception("Signable models can not be modified")
		# Get the last signature on this signable object
		self.predecessor = Signature.objects.filter(
			signable_type=self.signable_type,
			signable_id=self.signable_id
		).order_by('date_signed').last()
		# Save the current signature
		super().save(*args, **kwargs)
	
	def __str__(self):
		actor = self.metadata.get('acting_as', '').upper()
		return f"{actor}: {self.signer.username} on {self.signable} [{'ACCEPTED' if self.accepted else 'REJECTED'}]"
	
@receiver(post_delete, sender=Signature)
def delete_signature_hook(sender, instance, using, **kwargs):
	# Reset the current pending signatory of the signable object
	try:
		instance.signable.reset_current_pending_signatory()
	except Exception as e:
		return False
	
	return True


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
