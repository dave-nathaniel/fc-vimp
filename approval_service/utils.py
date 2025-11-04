# Utility functions for the approval service
from django.contrib.auth import get_user_model

User = get_user_model()

class ApprovalUtilities:
	"""
		A class containing utility functions for the approval service.
	"""

	def __init__(self, _signable: dict):
		# The signable object as a dictionary
		self.signable = _signable.get('class')
		# The class of the signable object
		self.signable_class = _signable.get('class')
		# The app label of the signable object
		self.signable_app_label = _signable.get('app_label', str(self.signable_class._meta))
		# The signatories of the signable object
		self.signatories = _signable.get('signatories', self.signable_class.signatories)

	def get_related_permissions(self, user: User) -> list:
		"""
			Get the related permissions for the user.
		"""
		# Get user permissions efficiently
		return sorted(
			list(
				set(
					[i.split('.')[1] for i in user.get_all_permissions() if i.startswith(f"{self.signable_app_label}.")]
				)
			)
		)

	def get_relevant_permissions(self, user: User) -> list:
		"""
			Get the relevant permissions for the user to sign the signable object.
		"""
		return sorted(
			list(set(self.signatories) & set(self.get_related_permissions(user)))
		)