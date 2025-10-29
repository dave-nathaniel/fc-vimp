from django.contrib.contenttypes.models import ContentType
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from rest_framework import status
from rest_framework.decorators import permission_classes, authentication_classes, api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from invoice_service.serializers import InvoiceSerializer
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Q, Prefetch, Count, Exists, OuterRef, Value, Subquery, IntegerField, QuerySet
from functools import reduce
import operator
from rest_framework.request import Request

from django.core.cache import cache

# Import optimization utilities
from core_service.cache_utils import (
    cache_result, CacheManager, get_or_set_cache, 
    invalidate_user_cache, CachedPagination
)

from .models import Keystore, Signature
from .serializers import SignatureSerializer
from invoice_service.models import Invoice, WORKFLOW_RULES
from overrides.rest_framework import APIResponse, CustomPagination

paginator = CustomPagination()

def get_signable_class(target_class: str) -> object:
	"""Optimized signable class mapping with caching."""
	# Cache the mapping to avoid repeated dictionary lookups
	cache_key = f"signable_class_mapping_{target_class}"
	
	def _get_mapping():
		signable_class_mapping = {
			'invoice': {
				"class": Invoice,
				"app_label": "invoice_service",
				"serializer": InvoiceSerializer,
				"order_by": "date_created",  # Default: oldest first (ascending)
				"signatories": list({role for v in WORKFLOW_RULES.values() for role in v["roles"]})
			}
		}
		return signable_class_mapping.get(target_class, False)
	
	return get_or_set_cache(
		cache_key, 
		_get_mapping, 
		# Cache till it is invalidated
		timeout=None
	)


def make_request_signable_queryset_key(
	request: Request,
	signable_class: object,
	status_filter: str,
	verdict_filter: str,
	order_by: str,
	related_permissions: list,
) -> str:
	# Stable, user-specific cache key for the full paginated payload
	return CacheManager.get_user_cache_key(
		request.user,
		"signable_queryset",
		str(signable_class._meta),
		status_filter,
		verdict_filter or "any",
		request.query_params.get('page', '1'),
		request.query_params.get('size', '15'),
		order_by,
	)

def make_base_signable_queryset_key(signable_class: object, relevant_permissions: list) -> str:
	# This key is used to cache the base signable queryset
	return CacheManager.generate_cache_key(
		CacheManager.PREFIX_SIGNABLE,
		str(signable_class._meta),
		'_'.join(relevant_permissions)
	)

def make_base_signable_queryset(signable_class: object, relevant_permissions: list) -> QuerySet:
	# This function is used to create the base signable queryset with efficient joins
	q_objects = [Q(signatories__contains=perm) for perm in relevant_permissions]
	query = reduce(operator.or_, q_objects)
	return (
		signable_class.objects.select_related(
			'purchase_order',
			'purchase_order__vendor',  # vendor directly via PO
			'grn',
			'grn__purchase_order',
			'grn__purchase_order__vendor',  # vendor via GRN->PO
		)
		.prefetch_related(
			'invoice_line_items',
			'invoice_line_items__po_line_item',
			'invoice_line_items__grn_line_item',
		)
		.filter(query)
		.distinct()
	)


class KeystoreAPIView(APIView):
	"""
	Optimized keystore API with caching and performance monitoring.
	"""
	authentication_classes = [AdfsAccessTokenAuthentication]
	permission_classes = (IsAuthenticated,)
	
	def get(self, request):
		"""Returns the cached public key of the authenticated user."""
		# Cache user's keystore lookup
		cache_key = CacheManager.get_user_cache_key(
			request.user, "keystore", request.user.id
		)
		
		def _get_keystore():
			try:
				keystore = Keystore.objects.select_related('user').get(user=request.user)
				return keystore.public_key
			except Keystore.DoesNotExist:
				return None
		
		public_key = get_or_set_cache(
			cache_key,
			_get_keystore,
			CacheManager.TIMEOUT_MEDIUM
		)
		
		if public_key is None:
			return APIResponse(
				f"A Keystore was not found for this user.", 
				status=status.HTTP_404_NOT_FOUND
			)
		
		return APIResponse(public_key, status=status.HTTP_200_OK)
	
	def post(self, request):
		"""Creates a new Keystore for the authenticated user."""
		# Invalidate user's keystore cache when creating new keystore
		cache_key = CacheManager.get_user_cache_key(
			request.user, "keystore", request.user.id
		)
		cache.delete(cache_key)
		
		# Implementation for creating keystore...
		return APIResponse("Keystore created.", status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def sign_signable_view(request, target_class, object_id):
	"""
	Optimized signing with caching and bulk operations.
	"""
	
	# Cache target class lookup
	target = get_signable_class(target_class)
	
	if not target:
		return APIResponse(
			f"A signable object of type {target_class} was not found.", 
			status=status.HTTP_404_NOT_FOUND
		)
	
	signable_class = target.get("class")
	signable_app_label = target.get("app_label")
	
	# Check permissions (cached)
	permission_key = f"user_permission_{request.user.id}_{signable_app_label}_can_sign_signable"
	has_permission = get_or_set_cache(
		permission_key,
		lambda: request.user.has_perm(f"{signable_app_label}.can_sign_signable"),
		CacheManager.TIMEOUT_MEDIUM
	)
	
	if not has_permission:
		return APIResponse(
			f"You do not have permission to sign this {signable_class} object.", 
			status=status.HTTP_403_FORBIDDEN
		)
	
	# Get signable object with optimized query
	try:
		signable = signable_class.objects.select_related().get(id=object_id)
	except ObjectDoesNotExist:
		return APIResponse(
			f"No {target_class} found with ID {object_id}.", 
			status=status.HTTP_404_NOT_FOUND
		)
	
	try:
		# Sign the object
		signable.sign(request)
		
		# Invalidate related caches
		invalidate_user_cache(request.user.id, "signables")
		CacheManager.invalidate_pattern(f"*{target_class}*")
		
	except PermissionError:
		return APIResponse(
			f"You do not have permission to sign this {target_class} object.", 
			status=status.HTTP_403_FORBIDDEN
		)
	except ValidationError as ve:
		return APIResponse(
			f"Unable to sign this {target_class} object: {ve}", 
			status=status.HTTP_400_BAD_REQUEST
		)
	except Exception as e:
		return APIResponse(
			f"Internal Error: {e}", 
			status=status.HTTP_500_INTERNAL_SERVER_ERROR
		)
	
	return APIResponse(message="Successful.", status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def get_user_signable_view(request, target_class, status_filter="all"):
	"""
		Enterprise-optimized user signable retrieval with:
		- Database-level filtering
		- Bulk signature loading
		- Intelligent caching
		- N+1 query elimination
	"""
	target = get_signable_class(target_class)

	if not target:
		return APIResponse(
			f"No signable object of type {target_class}.", 
			status=status.HTTP_400_BAD_REQUEST
		)
	
	signable_class = target.get("class")
	signable_app_label = target.get("app_label")
	signable_serializer = target.get("serializer")

	# Allow query parameter override for ordering (default: oldest first)
	# Examples: ?order_by=-date_created (newest first), ?order_by=id (by ID)
	order_by = request.query_params.get('order_by', target.get("order_by"))
	
	try:
		# Create cache key for this specific request
		page = request.query_params.get('page', '1')
		page_size = request.query_params.get('size', '15')
		verdict_filter = request.query_params.get("approved", "")

		# Get user permissions efficiently (cached)
		related_permissions = sorted(
			list(
				set(
					[i.split('.')[1] for i in request.user.get_all_permissions() if i.startswith(f"{signable_app_label}.")]
				)
			)
		)

		# Build a stable, user-specific cache key for the full paginated payload
		request_queryset_key = make_request_signable_queryset_key(
			request,
			signable_class,
			status_filter,
			verdict_filter,
			order_by,
			related_permissions,
		)

		# Fast path: return cached payload if available
		cached_payload = cache.get(request_queryset_key)
		if cached_payload is not None:
			return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=cached_payload)

		# Get the relevant permissions
		relevant_permissions = get_or_set_cache(
			CacheManager.generate_cache_key("user_permissions", request.user.id,signable_app_label),
			lambda: sorted(
				list(set(target.get("signatories")) 
				& set(related_permissions))
			),
			CacheManager.TIMEOUT_LONG
		)

		# Cache the queryset builder function
		base_queryset_cache_key = make_base_signable_queryset_key(signable_class, relevant_permissions)
		base_queryset = get_or_set_cache(
			base_queryset_cache_key, 
			lambda: make_base_signable_queryset(signable_class, relevant_permissions),
			CacheManager.TIMEOUT_LONG
		)

		# Get content type for signatures
		content_type = ContentType.objects.get_for_model(signable_class)
		signables_queryset = base_queryset.annotate(
			user_has_signed=Exists(
				Signature.objects.filter(
					signable_type=content_type,
					signable_id=OuterRef('pk'),
					signer=request.user
				)
			)
		)

		# Apply status filters at database level
		if status_filter == "pending":
			# Only objects where user has required permission for current step
			signables_queryset = signables_queryset.filter(
				current_pending_signatory__in=relevant_permissions
			)
		elif status_filter == "completed":
			signables_queryset = signables_queryset.filter(
				user_has_signed=True
			)
		
		
		# Apply approval filter if provided
		if verdict_filter:
			verdict_bool = bool(int(verdict_filter))
			signatures_queryset = Signature.objects.filter(
				accepted=verdict_bool
			)
			signables_queryset = signables_queryset.filter(
				id__in=signatures_queryset.values_list('signable_id', flat=True)
			)
		
		# Order the queryset
		signables_queryset = signables_queryset.order_by(order_by)

		# Fast path for count-only requests (e.g., size=1) to avoid heavy serialization
		if page_size == '1' or page_size == 1:
			cache_key_suffix = f"user_{request.user.id}_{target_class}_{status_filter}_approved_{verdict_filter or 'any'}_order_{order_by}"
			total_count = CachedPagination.cache_page_count(signables_queryset, cache_key_suffix)
			paginated_data = {'count': total_count, 'next': None, 'previous': None, 'results': []}
			cache.set(request_queryset_key, paginated_data, CacheManager.TIMEOUT_SHORT)
			return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
		
		# Paginate efficiently - CustomPagination now automatically computes and caches the true count
		paginated = paginator.paginate_queryset(signables_queryset, request)

		# Prefetch all signatures for the paginated objects in a single query to avoid N+1
		from collections import defaultdict
		ids = [obj.id for obj in paginated]
		signatures_by_id = defaultdict(list)
		if ids:
			signature_list = Signature.objects.select_related('signer', 'predecessor').filter(
				signable_type=content_type,
				signable_id__in=ids,
			).order_by('-date_signed')
			for sig in signature_list:
				signatures_by_id[sig.signable_id].append(sig)

		# Serialize with prefetched data and pass signatures map via context
		serialized_signables = signable_serializer(
			paginated, many=True, context={'signatures_by_id': dict(signatures_by_id)}
		).data
		
		# Build paginated payload
		paginated_data = paginator.get_paginated_response(serialized_signables).data
		
		# Cache the full paginated payload for consistent consumer experience
		cache.set(request_queryset_key, paginated_data, CacheManager.TIMEOUT_MEDIUM)
		
		return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
		
	except Exception as e:
		raise e
		return APIResponse(
			f"Internal Error: {e}", 
			status=status.HTTP_500_INTERNAL_SERVER_ERROR
		)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def get_signable_view(request, target_class, status_filter="all"):
	"""
	Enterprise-optimized signable retrieval for all objects.
	"""
	target = get_signable_class(target_class)
	
	if not target:
		return APIResponse(
			f"No signable object of type {target_class}.", 
			status=status.HTTP_400_BAD_REQUEST
		)
	
	signable_class = target.get("class")
	signable_serializer = target.get("serializer")

	# Allow query parameter override for ordering (default: oldest first)
	order_by = request.query_params.get('order_by', target.get("order_by"))

	try:
		# Create cache key for this specific request
		page = request.query_params.get('page', '1')
		page_size = request.query_params.get('size', '15')
		verdict_filter = request.GET.get("approved", "")
		cache_key = f"all_signables_{target_class}_{status_filter}_page_{page}_size_{page_size}_approved_{verdict_filter}_order_{order_by}"
		
		# Try to get cached data first
		cached_data = cache.get(cache_key)
		if cached_data is not None:
			return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=cached_data)
		
		# Get content type for efficient signature counting
		content_type = ContentType.objects.get_for_model(signable_class)
		
		# Build optimized queryset with database-level filtering
		signables_queryset = signable_class.objects.select_related().annotate(
			last_signature_accepted=Subquery(
				Signature.objects.filter(
					signable_type=content_type,
					signable_id=OuterRef('pk')
				).order_by('-date_signed').values('accepted')[:1]
			)
		)
		
		# Apply status filters at database level 
		# Note: For simplicity, we'll handle completion status in Python
		# since determining "complete" requires knowledge of workflow requirements
		
		# Apply approval filter
		if verdict_filter:
			verdict_bool = bool(int(verdict_filter))
			signables_queryset = signables_queryset.filter(
				last_signature_accepted=verdict_bool
			)
		
		# Order and paginate
		signables_queryset = signables_queryset.order_by(order_by)

		# Fast path for count-only requests (e.g., size=1) to avoid heavy serialization
		if page_size == '1' or page_size == 1:
			cache_key_suffix = f"{target_class}_{status_filter}_all_order_{order_by}_approved_{verdict_filter or 'any'}"
			total_count = CachedPagination.cache_page_count(signables_queryset, cache_key_suffix)
			paginated_data = {'count': total_count, 'next': None, 'previous': None, 'results': []}
			cache.set(cache_key, paginated_data, CacheManager.TIMEOUT_SHORT)
			return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
		
		# Cache pagination count
		cache_key_suffix = f"{target_class}_{status_filter}_all_page_{page}_size_{page_size}_order_{order_by}"
		if verdict_filter:
			cache_key_suffix += f"_approved_{verdict_filter}"
		
		total_count = CachedPagination.cache_page_count(signables_queryset, cache_key_suffix)
		
		paginated = paginator.paginate_queryset(signables_queryset, request)

		# Prefetch all signatures for the paginated objects in a single query to avoid N+1
		from collections import defaultdict
		ids = [obj.id for obj in paginated]
		signatures_by_id = defaultdict(list)
		if ids:
			content_type = ContentType.objects.get_for_model(signable_class)
			signature_list = Signature.objects.select_related('signer', 'predecessor').filter(
				signable_type=content_type,
				signable_id__in=ids,
			).order_by('-date_signed')
			for sig in signature_list:
				signatures_by_id[sig.signable_id].append(sig)

		serialized_signables = signable_serializer(
			paginated, many=True, context={'signatures_by_id': dict(signatures_by_id)}
		).data
		paginated_data = paginator.get_paginated_response(serialized_signables).data
		
		# Cache the data (not the response object)
		cache.set(cache_key, paginated_data, CacheManager.TIMEOUT_SHORT)
		
		return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
		
	except Exception as e:
		return APIResponse(
			f"Internal Error: {e}", 
			status=status.HTTP_500_INTERNAL_SERVER_ERROR
		)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def track_signable_view(request, target_class, object_id):
	"""
	Optimized signature tracking with efficient queries and caching.
	"""
	target = get_signable_class(target_class)
	
	if not target:
		return APIResponse(
			f"No signable object of type {target_class}.", 
			status=status.HTTP_400_BAD_REQUEST
		)
	
	signable_class = target.get("class")
	
	try:
		# Verify object exists first (cached)
		object_exists_key = f"signable_exists_{target_class}_{object_id}"
		object_exists = get_or_set_cache(
			object_exists_key,
			lambda: signable_class.objects.filter(id=object_id).exists(),
			CacheManager.TIMEOUT_MEDIUM
		)
		
		if not object_exists:
			return APIResponse(
				f"No {target_class} found with ID {object_id}.", 
				status=status.HTTP_404_NOT_FOUND
			)
		
		# Get content type efficiently (cached)
		content_type_key = f"content_type_{target_class}"
		content_type = get_or_set_cache(
			content_type_key,
			lambda: ContentType.objects.get_for_model(signable_class),
			CacheManager.TIMEOUT_LONG
		)
		
		# Get signatures with optimized query
		signatures_queryset = Signature.objects.select_related(
			'signer', 'predecessor'
		).filter(
			signable_type=content_type, 
			signable_id=object_id
		).order_by('-date_signed')
		
		# Cache pagination count
		page = request.query_params.get('page', '1')
		page_size = request.query_params.get('size', '15')
		cache_key_suffix = f"signatures_{target_class}_{object_id}_page_{page}_size_{page_size}"
		
		total_count = CachedPagination.cache_page_count(signatures_queryset, cache_key_suffix)
		
		# Paginate efficiently
		paginated = paginator.paginate_queryset(signatures_queryset, request, order_by='-date_signed')
		serialized_signatures = SignatureSerializer(paginated, many=True).data
		paginated_data = paginator.get_paginated_response(serialized_signatures).data
		
		return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
		
	except Exception as e:
		return APIResponse(
			f"Internal Error: {e}", 
			status=status.HTTP_500_INTERNAL_SERVER_ERROR
		)


# Utility functions for cache management
def invalidate_approval_caches(target_class: str, user_id: int = None):
	"""Invalidate all approval-related caches for a target class."""
	patterns_to_invalidate = [
		f"*{target_class}*",
		f"*signables*",
		f"*signatures*",
		f"*signable_queryset*",
	]
	
	for pattern in patterns_to_invalidate:
		CacheManager.invalidate_pattern(pattern)
	
	if user_id:
		invalidate_user_cache(user_id, "signables")
		invalidate_user_cache(user_id, "permissions")
		invalidate_user_cache(user_id, "signable_queryset")


def warm_approval_caches(user, target_class: str):
	"""Pre-warm caches for a user's approval data."""
	try:
		# Pre-warm user permissions
		target = get_signable_class(target_class)
		if target:
			signable_app_label = target.get("app_label")
			user_permissions_key = f"user_permissions_{user.id}_{signable_app_label}"
			
			permissions = [
				p.split('.')[1] for p in user.get_all_permissions() 
				if p.startswith(f"{signable_app_label}.")
			]
			cache.set(user_permissions_key, permissions, CacheManager.TIMEOUT_MEDIUM)
		
		return True
	except Exception:
		return False