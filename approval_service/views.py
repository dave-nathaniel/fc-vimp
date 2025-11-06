from django.contrib.contenttypes.models import ContentType
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from rest_framework import status
from rest_framework.decorators import permission_classes, authentication_classes, api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from invoice_service.serializers import InvoiceSerializer
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Q, Prefetch, Count, Exists, OuterRef, Value, Subquery, IntegerField, QuerySet, Sum, BooleanField
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
from collections import defaultdict
from .utils import ApprovalUtilities


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

	approval_utilities = ApprovalUtilities(target)
	
	try:
		# Create cache key for this specific request
		page = request.query_params.get('page', '1')
		page_size = request.query_params.get('size', '15')
		verdict_filter = request.query_params.get("approved", "")
		# Compute the relevant permissions for the user's role (intersection with target signatories)
		relevant_permissions = approval_utilities.get_relevant_permissions(request.user)
		# Get content type for signatures
		content_type = ContentType.objects.get_for_model(signable_class)
		# Make the base signable queryset
		signables_queryset = make_base_signable_queryset(signable_class, content_type, relevant_permissions)

		# signables_queryset = signables_queryset

		# Apply status filters at database level
		if status_filter == "pending":
			# Only objects where user has required permission for current step
			signables_queryset = signables_queryset.filter(
				current_pending_signatory__in=relevant_permissions
			)
			# Status: pending
		elif status_filter == "completed":
			signables_queryset = signables_queryset.filter(
				user_has_signed=True
			)
			# Status: completed
		
		# Apply approval filter if provided
		if verdict_filter:
			verdict_bool = bool(int(verdict_filter))
			signatures_queryset = Signature.objects.filter(
				accepted=verdict_bool
			)
			signables_queryset = signables_queryset.filter(
				id__in=signatures_queryset.values_list('signable_id', flat=True)
			)
			# Verdict filter applied
		
		# Order the queryset
		order_by = request.query_params.get('order_by', target.get("order_by"))
		signables_queryset = signables_queryset.order_by(order_by)

		# Fast path for count-only requests (e.g., size=1) to avoid heavy serialization
		if page == '1' and page_size == '1':
			paginated_data = {'count': signables_queryset.count(), 'next': None, 'previous': None, 'results': []}
			return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
		
		# Paginate efficiently - CustomPagination now automatically computes and caches the true count
		paginated = paginator.paginate_queryset(signables_queryset, request)

		# Prefetch all signatures for the paginated objects in a single query to avoid N+1
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
		
		return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)
		
	except Exception as e:
		# raise e
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def get_signable_summary_view(request, target_class):
	"""
		Get a summarized report of signables for the user including:
		- Total number of signables
		- Total number of signables rejected
		- Total number of signables accepted
		- Total number of signables pending
		- Total number of signables completed
		- Top 10 most recent pending signables
	"""
	target = get_signable_class(target_class)
	
	if not target:
		return APIResponse(
			f"No signable object of type {target_class}.", 
			status=status.HTTP_400_BAD_REQUEST
		)
	
	signable_serializer, signable_class = target.get("serializer"), target.get("class")

	# Get the relevant permissions for the user's role
	approval_utilities = ApprovalUtilities(target)

	relevant_permissions = approval_utilities.get_relevant_permissions(request.user)
	# Get content type for signatures
	content_type = ContentType.objects.get_for_model(signable_class)

	# Base queryset carrying all signables relevant to the user's roles
	summary_queryset = make_base_signable_queryset(signable_class, content_type, relevant_permissions)

	# Annotate whether the latest signature on each signable was accepted or rejected
	latest_sig_sub = Signature.objects.filter(
			signable_type=content_type,
			signable_id=OuterRef('pk'),
			metadata__acting_as__in=relevant_permissions # Filter by the user's relevant permissions
		).order_by('-date_signed').values('accepted')[:1]
	summary_queryset = summary_queryset.annotate(
		last_signature_accepted=Subquery(latest_sig_sub, output_field=BooleanField())
	)
 
	# Single aggregate to fetch all required counters in one DB hit
	counters = summary_queryset.aggregate(
		total_count=Count('id'),
		pending_count=Count('id', filter=Q(current_pending_signatory__in=relevant_permissions)),
		completed_count=Count('id', filter=Q(user_has_signed=True)), # User role
		rejected_count=Count('id', filter=Q(last_signature_accepted=False)),
		accepted_count=Count('id', filter=Q(last_signature_accepted=True)),
	)

	# Top-10 most recent pending signables (uses same base queryset, no extra annotations)
	recent_pending_signables = (
		summary_queryset
		.filter(current_pending_signatory__in=relevant_permissions)
		.order_by('-date_created')[:10]
	)
	serialized_recent_pending_signables = signable_serializer(recent_pending_signables, many=True).data

	return APIResponse(
		"Data retrieved.",
		status=status.HTTP_200_OK,
		data={
			**counters,
			"recent_pending_signables": serialized_recent_pending_signables,
		},
	)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def search_signables_view(request, target_class):
	"""
		Flexible multi-parameter search over signables of given class and user's role, paginated.
		Supported query params (all optional):
		- q: free text, searches description, external_document_id, payment_reason
		- po: purchase order id (exact)
		- grn: goods received note id or number (exact)
		- status: 'pending','completed','approved','declined','all'
		- from_date, to_date: invoice creation range
		- min_total, max_total: net total filter
	"""
	target = get_signable_class(target_class)
	if not target:
		return APIResponse(f"No signable object of type {target_class}.", status=status.HTTP_400_BAD_REQUEST)

	signable_serializer, signable_class = target.get("serializer"), target.get("class")
	relevant_permissions = sorted(list(set(target.get("signatories")) & set([
		i.split(".")[1]
		for i in request.user.get_all_permissions()
		if i.startswith(f"{target.get('app_label')}.")
	])))
	content_type = ContentType.objects.get_for_model(signable_class)

	qs = signable_class.objects.all()
	# Restrict to signables for relevant roles
	qs = qs.filter(signatories__contains=relevant_permissions)

	# Query params
	q = request.query_params.get("q", "").strip()
	po = request.query_params.get("po", "").strip()
	grn = request.query_params.get("grn", "").strip()
	status_str = request.query_params.get("status", "all").strip().lower()
	from_date = request.query_params.get("from_date")
	to_date = request.query_params.get("to_date")
	min_total = request.query_params.get("min_total")
	max_total = request.query_params.get("max_total")

	if q:
		qs = qs.filter(
			Q(description__icontains=q)
			| Q(external_document_id__icontains=q)
			| Q(payment_reason__icontains=q)
			| Q(purchase_order__vendor__name__icontains=q)
			| Q(purchase_order__vendor__internal_id__icontains=q)
			| Q(purchase_order__vendor__email__icontains=q)
		)
	if po:
		qs = qs.filter(purchase_order__po_id=po)
	if grn:
		qs = qs.filter(grn__grn_number__icontains=grn) | qs.filter(grn__id=grn)
	if from_date:
		qs = qs.filter(date_created__date__gte=from_date)
	if to_date:
		qs = qs.filter(date_created__date__lte=to_date)
	if min_total:
		qs = qs.filter(net_total__gte=min_total)
	if max_total:
		qs = qs.filter(net_total__lte=max_total)

	# Status logic
	if status_str == "pending":
		qs = qs.filter(current_pending_signatory__in=relevant_permissions)
	elif status_str == "completed":
		qs = qs.annotate(
			user_has_signed=Exists(
				Signature.objects.filter(
					signable_type=content_type,
					signable_id=OuterRef('pk'),
					metadata__acting_as__in=relevant_permissions
				)
			)
		).filter(user_has_signed=True)
	elif status_str == "approved":
		qs = qs.annotate(
			last_signature_accepted=Subquery(
				Signature.objects.filter(
					signable_type=content_type,
					signable_id=OuterRef('pk')
				).order_by('-date_signed').values('accepted')[:1],
				output_field=BooleanField(),
			)
		).filter(last_signature_accepted=True)
	elif status_str == "declined":
		qs = qs.annotate(
			last_signature_accepted=Subquery(
				Signature.objects.filter(
					signable_type=content_type,
					signable_id=OuterRef('pk')
				).order_by('-date_signed').values('accepted')[:1],
				output_field=BooleanField(),
			)
		).filter(last_signature_accepted=False)
	# 'all' returns everything for the role

	# Efficient select/prefetch based on existing logic
	qs = qs.select_related('purchase_order','purchase_order__vendor','grn','grn__purchase_order','grn__purchase_order__vendor')\
		.prefetch_related('invoice_line_items','invoice_line_items__po_line_item','invoice_line_items__grn_line_item','grn__line_items','grn__line_items__purchase_order_line_item__delivery_store','grn__line_items__invoice_items')

	qs = qs.order_by(request.query_params.get('order_by','-date_created'))

	# Pagination
	page = int(request.query_params.get('page',1))
	size = int(request.query_params.get('size',15))
	start = (page-1)*size
	end = start+size
	total_count = qs.count()
	data = signable_serializer(qs[start:end], many=True).data
	return APIResponse(
		"Search results.",
		status=status.HTTP_200_OK,
		data={"count": total_count, "results": data}
	)



# Utility functions
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


def make_request_signable_queryset_key( request: Request, signable_class: object, status_filter: str, verdict_filter: str, order_by: str, related_permissions: list) -> str:
	# Stable, user-specific cache key for the full paginated payload
	return CacheManager.get_user_cache_key(
		request.user,
		"signable_queryset",
		str(signable_class._meta),
		status_filter,
		verdict_filter or "",
		order_by,
	)


def make_base_signable_queryset_key(signable_class: object, relevant_permissions: list) -> str:
	# This key is used to cache the base signable queryset
	return CacheManager.generate_cache_key(
		CacheManager.PREFIX_SIGNABLE,
		str(signable_class._meta),
		'_'.join(relevant_permissions)
	)


def make_base_signable_queryset(signable_class: object, content_type: ContentType, relevant_permissions: list) -> QuerySet:
	q_objects = [Q(signatories__contains=perm) for perm in relevant_permissions]
	query = reduce(operator.or_, q_objects)
	return signable_class.objects.select_related(
			'purchase_order',
			'purchase_order__vendor',  # vendor directly via PO (needed for vendor serializer)
			'grn',
			'grn__purchase_order',
			'grn__purchase_order__vendor',
		).prefetch_related(
			'invoice_line_items',
			'invoice_line_items__po_line_item',
			'invoice_line_items__grn_line_item',
			'grn__purchase_order__line_items',
			'grn__purchase_order__line_items__delivery_store',
			'grn__purchase_order__line_items__grn_line_item',
			# Prefetch GRN line items and their delivery stores to support GRN.stores property
			'grn__line_items',
			'grn__line_items__purchase_order_line_item__delivery_store',
			'grn__line_items__invoice_items',
		).distinct().filter(
			# signatories__contains=relevant_permissions
			query
		).annotate(
			gross_total_annotated=Sum('invoice_line_items__gross_total'),
			total_tax_amount_annotated=Sum('invoice_line_items__tax_amount'),
			net_total_annotated=Sum('invoice_line_items__net_total'),
			user_has_signed=Exists(
				Signature.objects.filter(
					signable_type=content_type,
					signable_id=OuterRef('pk'),
					metadata__acting_as__in=relevant_permissions
				)
			)
		)