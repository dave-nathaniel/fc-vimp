from rest_framework.response import Response
from rest_framework import pagination, serializers
from rest_framework.pagination import PageNumberPagination

class APIResponse(Response):
	def __init__(self, message: object, status: object, **kwargs: object) -> object:
		response_data = {
			'message': message,
		}

		data = kwargs.get("data")
		response_data.update({"data": data}) if data else None

		if status in range(200, 299):
			response_data["status"] = "success"
		else:
			response_data["status"] = "failed"

		super().__init__(response_data, status=status)


class CustomPagination(PageNumberPagination):
	page_query_param = "page"
	page_size_query_param = "size"
	page_size = 15  # Default page size from settings
	max_page_size = 100  # Increased from 30 for better flexibility

	def paginate_queryset(self, queryset, request, view=None, order_by=None):
		# Handle both QuerySets and regular lists
		if hasattr(queryset, 'order_by'):
			# This is a Django QuerySet
			if order_by:
				queryset = queryset.order_by(order_by)
			elif hasattr(queryset, 'ordered') and not queryset.ordered:
				# Ensure queryset is ordered for consistent pagination
				queryset = queryset.order_by('id')
		# For regular lists, we don't need to apply ordering
		
		# Use parent method which efficiently applies LIMIT/OFFSET at database level
		page_size = self.get_page_size(request)
		if not page_size:
			return None

		paginator = self.django_paginator_class(queryset, page_size)
		page_number = self.get_page_number(request, paginator)

		try:
			# This efficiently fetches only the requested page from database
			self.page = paginator.page(page_number)
		except Exception as exc:
			msg = self.get_invalid_page_message(request, page_number, paginator)
			raise serializers.ValidationError(msg)

		if paginator.num_pages > 1 and self.template is not None:
			self.display_page_controls = True

		self.request = request
		return list(self.page)

	def get_page_size(self, request):
		# Support both 'size' and 'limit' query parameters for backward compatibility
		if self.page_size_query_param:
			page_size = request.query_params.get(self.page_size_query_param)
			if page_size:
				try:
					page_size = int(page_size)
					if page_size > 0:
						return min(page_size, self.max_page_size)
				except (KeyError, ValueError):
					pass
		
		# Also check for 'limit' parameter for backward compatibility
		limit = request.query_params.get('limit')
		if limit:
			try:
				limit = int(limit)
				if limit > 0:
					return min(limit, self.max_page_size)
			except (KeyError, ValueError):
				pass

		return self.page_size