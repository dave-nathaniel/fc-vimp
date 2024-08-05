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
	max_page_size  = 30

	def paginate_queryset(self, queryset, request, view=None, order_by=None):
		# Sort the queryset based on the 'order_by' query parameter, always show latest records first
		queryset = queryset.order_by(order_by) if order_by else queryset
		# Get 'limit' and 'offset' from request query parameters
		limit = request.query_params.get('limit')
		offset = request.query_params.get('offset')

		if limit:
			limit = int(limit)
			# Validate limit is within min and max limits
			if limit > self.max_limit:
				raise serializers.ValidationError({"limit": ["Limit should be less than or equal to {0}".format(self.max_limit)]})
			elif limit < self.min_limit:
				raise serializers.ValidationError({"limit": ["Limit should be greater than or equal to {0}".format(self.min_limit)]})

		if offset:
			offset = int(offset)
			# Validate offset is within min and max offsets
			if offset > self.max_offset:
				raise serializers.ValidationError({"offset": ["Offset should be less than or equal to {0}".format(self.max_offset)]})
			elif offset < self.min_offset:
				raise serializers.ValidationError({"offset": ["Offset should be greater than or equal to {0}".format(self.min_offset)]})

		return super(CustomPagination, self).paginate_queryset(queryset, request, view)