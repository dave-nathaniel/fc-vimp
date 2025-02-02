# forms.py

from django import forms
from egrn_service.models import get_conversion_methods, Conversion

class ConversionForm(forms.ModelForm):
	class Meta:
		model = Conversion
		fields = ['name', 'conversion_field', 'conversion_method']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		try:
			self.fields['conversion_method'].choices = get_conversion_methods()
		except Exception as e:
			print(f"Error fetching conversion methods: {e}")