from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import *

class ByDPostingStatusAdmin(ModelAdmin):
	search_fields = [
	    'content_type__model',  # Search by model name (e.g., "invoice", "goodsreceivednote")
	    'object_id',  # Search by related object ID
	    'status',  # Search by status (e.g., "failed", "success")
	    'error_message__icontains',  # Search in the error message field
	    'request_payload__icontains',  # Search within JSON request payload
	    'response_data__icontains',  # Search within JSON response data
	]


# Register your models here.
admin.site.register(ByDPostingStatus, ByDPostingStatusAdmin)