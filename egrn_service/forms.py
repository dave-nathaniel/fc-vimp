# forms.py

from django import forms
from .models import get_conversion_methods, Conversion

class ConversionForm(forms.ModelForm):
	class Meta:
		model = Conversion
		fields = ['name', 'conversion_field', 'conversion_method']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['conversion_method'].choices = get_conversion_methods()
