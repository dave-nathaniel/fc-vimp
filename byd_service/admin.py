import logging
from django.contrib import admin, messages
from django.urls import path
from django.utils.html import format_html
from django.shortcuts import redirect
from unfold.admin import ModelAdmin
from django_q.tasks import async_task

from .models import *


def retry_failed_posting():
	"""
		Retries all failed postings in ByDPostingStatus.
	"""
	
	logging.info("Retrying all failed postings...")
	
	# Fetch all failed postings
	fails = ByDPostingStatus.objects.filter(
		status="failed",
		retry_count__lt=5,
	)

	if not fails.exists():
		logging.info("No failed postings to retry.")
		return False

	for failed in fails:
		item = failed.related_object  # Get the posting instance

		async_task(failed.django_q_task_name, item, q_options={
			'task_name': f'[Retry {failed.retry_count + 1}] Posting-{item.id}-on-ByD',
		})
		
	logging.info("Finished retrying failed postings.")
	
	return True


class ByDPostingStatusAdmin(ModelAdmin):
	search_fields = [
		'content_type__model',  # Search by model name (e.g., "invoice", "goodsreceivednote")
		'object_id',  # Search by related object ID
		'status',  # Search by status (e.g., "failed", "success")
		'error_message__icontains',  # Search in the error message field
		'request_payload__icontains',  # Search within JSON request payload
		'response_data__icontains',  # Search within JSON response data
	]
	list_display = ('item_object', 'status', 'retry_count', 'created_at', 'retry_button')
	actions = ['retry_selected_posting']
	
	def item_object(self, obj):
		return obj.related_object.__str__()

	def retry_button(self, obj):
		"""
			Adds a 'Retry Failed Postings' button to the Django Admin interface.
		"""
		
		return format_html(
			'<a class="bg-primary-600 border border-transparent font-medium px-3 py-2 rounded text-white" style="width: fit-content !important;" href="{}">Retry Failed</a>',
			f"/admin/byd_service/bydpostingstatus/retry-failed-posting/"
		) if obj.status in ["failed"] and obj.retry_count < 10 else ""

	retry_button.short_description = "Retry Posting"
	retry_button.allow_tags = True

	def retry_failed_posting_view(self, request):
		"""
			Custom Django Admin view to trigger retrying failed Posting.
		"""
		try:
			retry_failed_posting()
			self.message_user(request, "Retry process started successfully!", messages.SUCCESS)
		except Exception as e:
			logging.error(f"Error while retrying failed posting: {e}")
			self.message_user(request, f"Error: {e}", messages.ERROR)

		return redirect(request.META.get('HTTP_REFERER', '/admin/byd_service/bydpostingstatus/'))

	def get_urls(self):
		"""
			Add custom admin URLs.
		"""
		urls = super().get_urls()
		custom_urls = [
			path('retry-failed-posting/', self.admin_site.admin_view(self.retry_failed_posting_view),
				 name='retry-failed-posting'),
		]
		return custom_urls + urls

	def retry_selected_posting(self, request, queryset):
		"""
			Custom admin action to retry selected posting.
		"""
		fails = queryset.filter(status="failed")

		if not fails.exists():
			self.message_user(request, "No failed posting selected.", messages.WARNING)
			return

		for failed in fails:
			try:
				async_task(failed.django_q_task_name, failed.related_object, q_options={
					'task_name': f'[Retry {failed.retry_count + 1}] {failed.related_object.id}-on-ByD',
				})
				self.message_user(request, "Retry process started successfully!", messages.SUCCESS)
			except Exception as e:
				logging.error(f"Error while retrying failed postings: {e}")
				self.message_user(request, f"Error: {e}", messages.ERROR)

		self.message_user(request, "Selected posting retried successfully!", messages.SUCCESS)

	retry_selected_posting.short_description = "Retry selected failed postings"


# Register your models here.
admin.site.register(ByDPostingStatus, ByDPostingStatusAdmin)