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
			Adds a 'Retry' button for individual failed postings.
		"""
		if obj.status == "failed" and obj.retry_count < 5:
			return format_html(
				'<a class="bg-primary-600 border border-transparent font-medium px-3 py-2 rounded text-white" '
				'style="width: fit-content !important;" href="{}">Retry</a>',
				f"/API/admin/byd_service/bydpostingstatus/{obj.id}/retry-posting/"
			)
		return ""

	retry_button.short_description = "Retry Posting"
	retry_button.allow_tags = True

	def retry_all_failed_posting_view(self, request):
		"""
			Custom Django Admin view to trigger retrying all failed postings.
		"""
		try:
			if retry_failed_posting():
				self.message_user(request, "Retry process started for all failed postings!", messages.SUCCESS)
			else:
				self.message_user(request, "No failed postings to retry.", messages.INFO)
		except Exception as e:
			logging.error(f"Error while retrying all failed postings: {e}")
			self.message_user(request, f"Error: {e}", messages.ERROR)

		return redirect(request.META.get('HTTP_REFERER', '/API/admin/byd_service/bydpostingstatus/'))

	def retry_single_posting_view(self, request, posting_id):
		"""
			Custom Django Admin view to retry a single failed posting.
		"""
		try:
			posting = ByDPostingStatus.objects.get(id=posting_id)
			if posting.status == "failed" and posting.retry_count < 5:
				async_task(posting.django_q_task_name, posting.related_object, q_options={
					'task_name': f'[Retry {posting.retry_count + 1}] Posting-{posting.related_object.id}-on-ByD',
				})
				self.message_user(request, f"Retry process started for posting {posting_id}!", messages.SUCCESS)
			else:
				self.message_user(request, "This posting cannot be retried.", messages.WARNING)
		except ByDPostingStatus.DoesNotExist:
			self.message_user(request, "Posting not found.", messages.ERROR)
		except Exception as e:
			logging.error(f"Error while retrying posting {posting_id}: {e}")
			self.message_user(request, f"Error: {e}", messages.ERROR)

		return redirect(request.META.get('HTTP_REFERER', '/API/admin/byd_service/bydpostingstatus/'))

	def get_urls(self):
		"""
			Add custom admin URLs.
		"""
		urls = super().get_urls()
		custom_urls = [
			path('retry-all-failed/', self.admin_site.admin_view(self.retry_all_failed_posting_view),
				 name='retry-all-failed-posting'),
			path('<int:posting_id>/retry-posting/', self.admin_site.admin_view(self.retry_single_posting_view),
				 name='retry-single-posting'),
		]
		return custom_urls + urls

	def changelist_view(self, request, extra_context=None):
		"""
			Add a custom button to the changelist view.
		"""
		extra_context = extra_context or {}
		extra_context['show_retry_all_button'] = True
		extra_context['retry_all_url'] = '/API/admin/byd_service/bydpostingstatus/retry-all-failed/'
		return super().changelist_view(request, extra_context=extra_context)

	def retry_selected_posting(self, request, queryset):
		"""
			Custom admin action to retry selected postings.
		"""
		fails = queryset.filter(status="failed", retry_count__lt=5)

		if not fails.exists():
			self.message_user(request, "No eligible failed postings selected.", messages.WARNING)
			return

		for failed in fails:
			try:
				async_task(failed.django_q_task_name, failed.related_object, q_options={
					'task_name': f'[Retry {failed.retry_count + 1}] {failed.related_object.id}-on-ByD',
				})
			except Exception as e:
				logging.error(f"Error while retrying posting {failed.id}: {e}")
				self.message_user(request, f"Error retrying posting {failed.id}: {e}", messages.ERROR)
				continue

		self.message_user(request, f"Retry process started for {fails.count()} selected postings!", messages.SUCCESS)

	retry_selected_posting.short_description = "Retry selected failed postings"


# Register your models here.
admin.site.register(ByDPostingStatus, ByDPostingStatusAdmin)