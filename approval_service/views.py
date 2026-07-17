import operator
import os
from decimal import Decimal
from functools import reduce
from uuid import uuid4

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import (
	Q,
	Prefetch,
	Count,
	Exists,
	OuterRef,
	Value,
	Subquery,
	IntegerField,
	QuerySet,
	Sum,
	BooleanField,
)
from django.utils import timezone
from django_auth_adfs.rest_framework import AdfsAccessTokenAuthentication
from openpyxl import Workbook
from rest_framework import status
from rest_framework.decorators import permission_classes, authentication_classes, api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.views import APIView

from invoice_service.serializers import InvoiceSerializer

# Import optimization utilities
from core_service.cache_utils import (
	cache_result, CacheManager, get_or_set_cache, 
	invalidate_user_cache, CachedPagination
)

from .models import Keystore, Signature
from .serializers import SignatureSerializer
from invoice_service.models import Invoice, InvoiceLineItem, WORKFLOW_RULES
from overrides.rest_framework import APIResponse, CustomPagination
from collections import defaultdict
from .utils import ApprovalUtilities


paginator = CustomPagination()

EXPORT_HEADERS = [
	"DATE",
	"VENDORS NAME",
	"BYD ID",
	"EXTERNAL ID",
	"GRN",
	"DESCRIPTION",
	"AMOUNT",
	"ITEMS",
	"STORE",
	"SENT BY",
	"SIGNATORIES",
]


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


# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# @authentication_classes([AdfsAccessTokenAuthentication])
# def sign_signable_view(request, target_class, object_id):
# 	"""
# 	Optimized signing with caching and bulk operations.
# 	"""
	
# 	# Cache target class lookup
# 	target = get_signable_class(target_class)
	
# 	if not target:
# 		return APIResponse(
# 			f"A signable object of type {target_class} was not found.", 
# 			status=status.HTTP_404_NOT_FOUND
# 		)
	
# 	signable_class = target.get("class")
# 	signable_app_label = target.get("app_label")
	
# 	# Check permissions (cached)
# 	permission_key = f"user_permission_{request.user.id}_{signable_app_label}_can_sign_signable"
# 	has_permission = get_or_set_cache(
# 		permission_key,
# 		lambda: request.user.has_perm(f"{signable_app_label}.can_sign_signable"),
# 		CacheManager.TIMEOUT_MEDIUM
# 	)
	
# 	if not has_permission:
# 		return APIResponse(
# 			f"You do not have permission to sign this {signable_class} object.", 
# 			status=status.HTTP_403_FORBIDDEN
# 		)
	
# 	# Get signable object with optimized query
# 	try:
# 		signable = signable_class.objects.select_related().get(id=object_id)
# 	except ObjectDoesNotExist:
# 		return APIResponse(
# 			f"No {target_class} found with ID {object_id}.", 
# 			status=status.HTTP_404_NOT_FOUND
# 		)
	
# 	try:
# 		# Sign the object
# 		signable.sign(request)
		
# 		# Invalidate related caches
# 		invalidate_user_cache(request.user.id, "signables")
# 		CacheManager.invalidate_pattern(f"*{target_class}*")
		
# 	except PermissionError:
# 		return APIResponse(
# 			f"You do not have permission to sign this {target_class} object.", 
# 			status=status.HTTP_403_FORBIDDEN
# 		)
# 	except ValidationError as ve:
# 		return APIResponse(
# 			f"Unable to sign this {target_class} object: {ve}", 
# 			status=status.HTTP_400_BAD_REQUEST
# 		)
# 	except Exception as e:
# 		return APIResponse(
# 			f"Internal Error: {e}", 
# 			status=status.HTTP_500_INTERNAL_SERVER_ERROR
# 		)
	
# 	return APIResponse(message="Successful.", status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def sign_signable_view(request, target_class):
	"""
	Optimized signing with caching and bulk operations.
	Supports signing multiple objects in a single request.
	"""
	
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
	
	# Accept either a single object_id or a list of object_ids
	object_ids = request.data.get("object_ids")
	if not object_ids:
		return APIResponse(
			"No object_ids provided.",
			status=status.HTTP_400_BAD_REQUEST
		)
	if not isinstance(object_ids, list):
		object_ids = [object_ids]
	
	signed = []
	failed = {}
	
	for object_id in object_ids:
		try:
			signable = signable_class.objects.select_related().get(id=object_id)
		except ObjectDoesNotExist:
			failed[object_id] = f"No {target_class} found with ID {object_id}."
			continue
		
		try:
			signable.sign(request)
			signed.append(object_id)
		except PermissionError:
			failed[object_id] = f"You do not have permission to sign this {target_class} object."
		except ValidationError as ve:
			failed[object_id] = f"Unable to sign this {target_class} object: {ve}"
		except Exception as e:
			failed[object_id] = f"Internal Error: {e}"
	
	# Invalidate related caches once, after processing the batch
	if signed:
		invalidate_user_cache(request.user.id, "signables")
		CacheManager.invalidate_pattern(f"*{target_class}*")
	
	if signed and not failed:
		return APIResponse(message="Successful.", status=status.HTTP_200_OK, data={"signed": signed})
	elif signed and failed:
		return APIResponse(message="Partially successful.", status=status.HTTP_207_MULTI_STATUS, data={"signed": signed, "failed": failed})
	else:
		return APIResponse(message="Failed to sign objects.", status=status.HTTP_400_BAD_REQUEST, data={"failed": failed})

		
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
		# Build a LIGHT queryset for filtering/pagination only (no Sum annotations,
		# no Exists, no prefetch, no DISTINCT). The expensive annotations/joins are
		# applied later, to only the paginated page, by hydrate_signables_by_ids.
		signables_queryset = make_filtered_signable_queryset(signable_class, relevant_permissions)

		# Apply status filters at database level
		if status_filter == "pending":
			# Only objects where user has required permission for current step
			signables_queryset = signables_queryset.filter(
				current_pending_signatory__in=relevant_permissions
			)
			# Status: pending
		elif status_filter == "completed":
			# "completed" == the user's role has already signed this signable. Express
			# this directly as a filter (cheap) rather than via the user_has_signed
			# annotation, which only exists on the heavy queryset.
			signables_queryset = signables_queryset.filter(
				Exists(
					Signature.objects.filter(
						signable_type=content_type,
						signable_id=OuterRef('pk'),
						metadata__acting_as__in=relevant_permissions,
					)
				)
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

		# Order the (light) queryset
		order_by = request.query_params.get('order_by', target.get("order_by"))
		signables_queryset = signables_queryset.order_by(order_by)

		# Fast path for count-only requests (e.g., size=1) to avoid heavy serialization
		if page == '1' and page_size == '1':
			paginated_data = {'count': signables_queryset.count(), 'next': None, 'previous': None, 'results': []}
			return APIResponse("Data retrieved.", status=status.HTTP_200_OK, data=paginated_data)

		# Paginate the LIGHT queryset (fast: LIMIT can short-circuit a single-table scan).
		paginated = paginator.paginate_queryset(signables_queryset, request)

		# Hydrate ONLY the paginated rows with the heavy annotations + prefetch, then
		# preserve page order. This is where the Sum/Exists/joins run - on <= page_size rows.
		ids = [obj.id for obj in paginated]
		paginated = hydrate_signables_by_ids(
			signable_class, content_type, relevant_permissions, ids, order_by
		)
		signatures_by_id = defaultdict(list)
		if ids:
			signature_list = Signature.objects.select_related('signer', 'predecessor').filter(
				signable_type=content_type,
				signable_id__in=ids,
			).order_by('-date_signed')
			for sig in signature_list:
				signatures_by_id[sig.signable_id].append(sig)

		# Build a {product_id: conversion_field} map once for the whole page so the
		# serializer's extra_fields does not run a ProductConfiguration query per line item.
		product_config_map = build_product_config_map(paginated)

		# Serialize with prefetched data and pass maps via context
		serialized_signables = signable_serializer(
			paginated,
			many=True,
			context={
				'signatures_by_id': dict(signatures_by_id),
				'product_config_map': product_config_map,
			},
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

	# Counters are computed cheaply, NOT via .aggregate(Count x5) over the heavy queryset
	# (which wrapped the Sum-annotated + DISTINCT + 6-way-joined queryset PLUS a per-row
	# correlated Subquery in COUNT(*), unbounded: measured at ~71 SECONDS).
	light = make_filtered_signable_queryset(signable_class, relevant_permissions)

	# total/pending/completed: scalar counts and an Exists() that short-circuits.
	total_count = light.count()
	pending_count = light.filter(current_pending_signatory__in=relevant_permissions).count()
	completed_count = light.filter(
		Exists(Signature.objects.filter(
			signable_type=content_type,
			signable_id=OuterRef('pk'),
			metadata__acting_as__in=relevant_permissions,
		))
	).count()

	# rejected/accepted ("latest signature among the user's roles was rejected/accepted"):
	# computing this as a per-invoice correlated ORDER BY subquery is pathological - the
	# JSON metadata__acting_as lookup is unindexable and "latest" can't short-circuit, so
	# it scans+sorts the whole Signature table PER invoice (~104s for the pair). Instead,
	# scan the relevant signatures ONCE and reduce to latest-per-signable in Python.
	signed_ids = set(
		light.filter(
			Exists(Signature.objects.filter(
				signable_type=content_type,
				signable_id=OuterRef('pk'),
				metadata__acting_as__in=relevant_permissions,
			))
		).values_list('id', flat=True)
	)
	latest_accepted_by_signable = {}
	if signed_ids:
		for signable_id, accepted in (
			Signature.objects
			.filter(signable_type=content_type, metadata__acting_as__in=relevant_permissions)
			.order_by('signable_id', '-date_signed')
			.values_list('signable_id', 'accepted')
		):
			# First row seen per signable_id is its latest signature (date_signed DESC).
			if signable_id not in latest_accepted_by_signable:
				latest_accepted_by_signable[signable_id] = accepted
	# Restrict to signables that are role-relevant (mirrors the old queryset scope).
	rejected_count = sum(
		1 for sid, acc in latest_accepted_by_signable.items()
		if sid in signed_ids and acc is False
	)
	accepted_count = sum(
		1 for sid, acc in latest_accepted_by_signable.items()
		if sid in signed_ids and acc is True
	)

	counters = {
		'total_count': total_count,
		'pending_count': pending_count,
		'completed_count': completed_count,
		'rejected_count': rejected_count,
		'accepted_count': accepted_count,
	}

	# Top-10 most recent pending signables: page the IDs cheaply on the light queryset,
	# then hydrate only those rows (annotations/prefetch) - same pattern as the list view,
	# keeping the serializer's N+1 fixes via the context maps.
	order_by = '-date_created'
	recent_ids = list(
		light.filter(current_pending_signatory__in=relevant_permissions)
		.order_by(order_by)
		.values_list('id', flat=True)[:10]
	)
	recent_pending_signables = hydrate_signables_by_ids(
		signable_class, content_type, relevant_permissions, recent_ids, order_by
	)

	# Prefetch signatures + product config map for the top-10, so get_workflow and
	# extra_fields resolve from cache instead of per-row queries.
	signatures_by_id = defaultdict(list)
	if recent_ids:
		for sig in Signature.objects.select_related('signer', 'predecessor').filter(
			signable_type=content_type, signable_id__in=recent_ids,
		).order_by('-date_signed'):
			signatures_by_id[sig.signable_id].append(sig)
	product_config_map = build_product_config_map(recent_pending_signables)

	serialized_recent_pending_signables = signable_serializer(
		recent_pending_signables,
		many=True,
		context={
			'signatures_by_id': dict(signatures_by_id),
			'product_config_map': product_config_map,
		},
	).data

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

	signable_class = target.get("class")
	signable_serializer = target.get("serializer")

	# Build a LIGHT filtered queryset (filters + ordering only, no Sum annotations, no
	# correlated subqueries, no prefetch). The status=approved/declined branches that
	# previously ran a per-row correlated ORDER BY subquery (the 71s pattern) are now
	# resolved to an id__in set inside the helper.
	qs, content_type, relevant_permissions = _build_search_signables_queryset(request, target)

	# Pagination: count + a single cheap page-of-ids slice on the light queryset (the
	# LIMIT short-circuits a single-table scan), then hydrate ONLY that page's rows.
	page = int(request.query_params.get('page', 1))
	size = int(request.query_params.get('size', 15))
	start = (page - 1) * size
	end = start + size
	total_count = qs.count()

	order_by = request.query_params.get('order_by', '-date_created')
	# page_ids is ALREADY in the authoritative paginated order (it came off the ordered,
	# sliced light queryset, including its compound -id tiebreak). hydrate's filter(id__in)
	# does not preserve order, so re-sort the hydrated objects to match page_ids positionally
	# rather than trusting a single-column re-order to reproduce the compound tiebreak.
	#
	# List full page rows then read ids in Python — do NOT .values_list('id') here: the q
	# free-text path applies .distinct(), and `SELECT DISTINCT id ... ORDER BY date_created`
	# raises MySQL 3065 (ORDER BY column not in SELECT list) under ONLY_FULL_GROUP_BY.
	# `SELECT DISTINCT * ... ORDER BY date_created` keeps the order column in the projection.
	# This mirrors get_user_signable_view and is only `size` rows.
	page_objs = list(qs[start:end])
	page_ids = [obj.id for obj in page_objs]
	paginated = hydrate_signables_by_ids(
		signable_class, content_type, relevant_permissions, page_ids, order_by
	)
	position = {sid: i for i, sid in enumerate(page_ids)}
	paginated.sort(key=lambda obj: position.get(obj.id, len(page_ids)))

	# Bulk-load the page's signatures and product config so the serializer resolves
	# workflow state / extra_fields from context instead of per-row model-property queries.
	signatures_by_id = defaultdict(list)
	if page_ids:
		signature_list = Signature.objects.select_related('signer', 'predecessor').filter(
			signable_type=content_type,
			signable_id__in=page_ids,
		).order_by('-date_signed')
		for sig in signature_list:
			signatures_by_id[sig.signable_id].append(sig)
	product_config_map = build_product_config_map(paginated)

	data = signable_serializer(
		paginated,
		many=True,
		context={
			'signatures_by_id': dict(signatures_by_id),
			'product_config_map': product_config_map,
		},
	).data
	return APIResponse(
		"Search results.",
		status=status.HTTP_200_OK,
		data={"count": total_count, "results": data}
	)


def _build_search_signables_queryset(request: Request, target: dict):
	signable_class = target.get("class")
	approval_utilities = ApprovalUtilities(target)
	relevant_permissions = approval_utilities.get_relevant_permissions(request.user)
	content_type = ContentType.objects.get_for_model(signable_class)

	queryset = signable_class.objects.all().filter(signatories__contains=relevant_permissions)

	q = request.query_params.get("q", "").strip()
	po = request.query_params.get("po", "").strip()
	grn = request.query_params.get("grn", "").strip()
	status_str = request.query_params.get("status", "all").strip().lower()
	from_date = request.query_params.get("from_date")
	to_date = request.query_params.get("to_date")
	min_total = request.query_params.get("min_total")
	max_total = request.query_params.get("max_total")

	if q:
		# q-search traverses line-item relations (1-to-many), which can duplicate
		# invoice rows; use DISTINCT only for this query shape.
		queryset = queryset.filter(
			Q(description__icontains=q)
			| Q(external_document_id__icontains=q)
			| Q(payment_reason__icontains=q)
			| Q(purchase_order__vendor__user__first_name__icontains=q)
			| Q(purchase_order__vendor__user__last_name__icontains=q)
			| Q(purchase_order__vendor__user__email__icontains=q)
			| Q(purchase_order__vendor__byd_internal_id__icontains=q)
			| Q(grn__line_items__purchase_order_line_item__delivery_store__store_name__icontains=q)
			| Q(grn__line_items__purchase_order_line_item__delivery_store__byd_cost_center_code__icontains=q)
		)
	if po:
		queryset = queryset.filter(purchase_order__po_id=po)
	if grn:
		queryset = queryset.filter(grn__grn_number__icontains=grn) | queryset.filter(grn__id=grn)
	if from_date:
		queryset = queryset.filter(date_created__date__gte=from_date)
	if to_date:
		queryset = queryset.filter(date_created__date__lte=to_date)
	if min_total:
		queryset = queryset.filter(net_total__gte=min_total)
	if max_total:
		queryset = queryset.filter(net_total__lte=max_total)

	if status_str == "pending":
		queryset = queryset.filter(current_pending_signatory__in=relevant_permissions)
	elif status_str == "completed":
		# "completed" == the user's role has signed. Direct Exists filter (short-circuits)
		# rather than an annotation, so it composes with the light queryset.
		queryset = queryset.filter(
			Exists(
				Signature.objects.filter(
					signable_type=content_type,
					signable_id=OuterRef('pk'),
					metadata__acting_as__in=relevant_permissions
				)
			)
		)
	elif status_str in ("approved", "declined"):
		# approved == "the latest signature on this invoice, BY ANYONE, was accepted=True";
		# declined == latest was accepted=False. (NB: this is role-UNSCOPED, unlike the
		# summary view's accepted/rejected counters — there is no metadata__acting_as here,
		# matching the original correlated subquery's semantics exactly.)
		#
		# The original used a per-row correlated ORDER BY subquery over Signatures, which
		# MySQL re-ran for every candidate invoice on the unindexable JSON-filtered set —
		# the same pattern that cost 71s in the summary view. Instead, scan the relevant
		# signatures ONCE (ordered signable_id, -date_signed so the first row per id is the
		# latest) and reduce the latest verdict per invoice in Python, then filter id__in.
		latest_accepted = {}
		for sid, accepted in (
			Signature.objects
			.filter(signable_type=content_type)
			.order_by('signable_id', '-date_signed')
			.values_list('signable_id', 'accepted')
		):
			latest_accepted.setdefault(sid, accepted)
		# `is True`/`is False` matches the SQL `=True`/`=False`, which excludes NULL
		# (a signature recorded with no verdict yet); a plain truthiness check would not.
		if status_str == "approved":
			verdict_ids = [sid for sid, acc in latest_accepted.items() if acc is True]
		else:
			verdict_ids = [sid for sid, acc in latest_accepted.items() if acc is False]
		queryset = queryset.filter(id__in=verdict_ids)

	order_by = request.query_params.get('order_by', '-date_created')
	secondary_order = '-id' if order_by.startswith('-') else 'id'
	queryset = queryset.order_by(order_by, secondary_order)
	if q:
		queryset = queryset.distinct()

	return queryset, content_type, relevant_permissions


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@authentication_classes([AdfsAccessTokenAuthentication])
def download_signables_excel_view(request, target_class):
	target = get_signable_class(target_class)
	if not target:
		return APIResponse(
			f"No signable object of type {target_class}.",
			status=status.HTTP_400_BAD_REQUEST
		)

	if target.get("class") is not Invoice:
		return APIResponse(
			"Excel export is currently supported for invoices only.",
			status=status.HTTP_400_BAD_REQUEST
		)

	try:
		queryset, content_type, _ = _build_search_signables_queryset(request, target)
		# Export ID collection should not inherit ORDER BY from the search queryset.
		# This avoids DISTINCT+ORDER BY SQL edge cases on strict MySQL modes.
		signable_ids = list(queryset.order_by().values_list('id', flat=True).distinct())

		if not signable_ids:
			return APIResponse(
				"No records matched the provided filters.",
				status=status.HTTP_200_OK,
				data={
					"download_url": None,
					"row_count": 0
				}
			)

		items_map, stores_map, amount_map = _collect_invoice_line_items(signable_ids)
		latest_signature_map, signatures_map = _collect_invoice_signatures(content_type, signable_ids)

		target_slug = target_class.lower().replace(" ", "_")
		file_path, row_count = _write_invoice_export_file(
			request,
			queryset,
			target_slug,
			amount_map,
			items_map,
			stores_map,
			latest_signature_map,
			signatures_map,
		)

		download_url = _build_media_download_url(request, file_path)

		return APIResponse(
			"Download ready.",
			status=status.HTTP_200_OK,
			data={
				"download_url": download_url,
				"row_count": row_count,
			}
		)
	except Exception as exc:
		return APIResponse(
			f"Internal Error: {exc}",
			status=status.HTTP_500_INTERNAL_SERVER_ERROR
		)


def _collect_invoice_line_items(invoice_ids: list):
	items_map = defaultdict(list)
	stores_map = defaultdict(list)
	amount_map = defaultdict(lambda: Decimal('0'))
	seen_stores = defaultdict(set)

	if not invoice_ids:
		return items_map, stores_map, amount_map

	line_items = InvoiceLineItem.objects.filter(invoice_id__in=invoice_ids).select_related(
		'po_line_item__delivery_store'
	).values(
		'invoice_id',
		'po_line_item__product_name',
		'po_line_item__delivery_store__store_name',
		'net_total',
	)

	for line_item in line_items.iterator(chunk_size=1000):
		invoice_id = line_item['invoice_id']
		product_name = line_item.get('po_line_item__product_name')
		if product_name:
			items_map[invoice_id].append(product_name)

		store_name = line_item.get('po_line_item__delivery_store__store_name')
		if store_name and store_name not in seen_stores[invoice_id]:
			stores_map[invoice_id].append(store_name)
			seen_stores[invoice_id].add(store_name)

		line_amount = line_item.get('net_total') or Decimal('0')
		amount_map[invoice_id] += line_amount

	return items_map, stores_map, amount_map


def _collect_invoice_signatures(content_type: ContentType, invoice_ids: list):
	latest_signature_map = {}
	signatures_map = defaultdict(list)

	if not invoice_ids:
		return latest_signature_map, signatures_map

	signatures = Signature.objects.select_related('signer').filter(
		signable_type=content_type,
		signable_id__in=invoice_ids
	).order_by('-date_signed')

	for signature in signatures.iterator(chunk_size=500):
		entry = _format_signature_entry(signature)
		if signature.signable_id not in latest_signature_map:
			latest_signature_map[signature.signable_id] = entry
		signatures_map[signature.signable_id].append(entry)

	return latest_signature_map, signatures_map


def _write_invoice_export_file(
	request: Request,
	queryset: QuerySet,
	target_slug: str,
	amount_map: dict,
	items_map: dict,
	stores_map: dict,
	latest_signature_map: dict,
	signatures_map: dict,
):
	download_dir = _ensure_download_dir(target_slug)
	user_identifier = getattr(request.user, 'id', None) or 'anonymous'
	filename = f"{target_slug}_signables_{user_identifier}_{timezone.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}.xlsx"
	file_path = os.path.join(download_dir, filename)

	workbook = Workbook(write_only=True)
	worksheet = workbook.create_sheet(title="Signables")
	worksheet.append(EXPORT_HEADERS)

	row_count = 0
	base_fields = (
		'id',
		'date_created',
		'purchase_order__vendor__user__first_name',
		'purchase_order__vendor__user__last_name',
		'purchase_order__vendor__user__username',
		'purchase_order__vendor__user__email',
		'purchase_order__vendor__byd_internal_id',
		'external_document_id',
		'grn__grn_number',
		'description',
	)

	for record in queryset.values(*base_fields).iterator(chunk_size=500):
		worksheet.append(
			_build_invoice_export_row(
				record,
				amount_map,
				items_map,
				stores_map,
				latest_signature_map,
				signatures_map,
			)
		)
		row_count += 1

	workbook.save(file_path)
	workbook.close()
	return file_path, row_count


def _build_invoice_export_row(
	record: dict,
	amount_map: dict,
	items_map: dict,
	stores_map: dict,
	latest_signature_map: dict,
	signatures_map: dict,
):
	invoice_id = record.get('id')
	amount_value = amount_map.get(invoice_id, Decimal('0'))
	grn_value = record.get('grn__grn_number')

	return [
		_format_datetime(record.get('date_created')),
		_format_vendor_name(record),
		record.get('purchase_order__vendor__byd_internal_id') or '',
		record.get('external_document_id') or '',
		grn_value if grn_value is not None else '',
		record.get('description') or '',
		amount_value,
		"\n".join(items_map.get(invoice_id, [])),
		"\n".join(stores_map.get(invoice_id, [])),
		latest_signature_map.get(invoice_id, ""),
		"\n".join(signatures_map.get(invoice_id, [])),
	]


def _format_vendor_name(record: dict) -> str:
	first_name = _safe_strip(record.get('purchase_order__vendor__user__first_name'))
	last_name = _safe_strip(record.get('purchase_order__vendor__user__last_name'))
	username = _safe_strip(record.get('purchase_order__vendor__user__username'))
	email = _safe_strip(record.get('purchase_order__vendor__user__email'))
	fallback = _safe_strip(record.get('purchase_order__vendor__byd_internal_id'))

	full_name = f"{first_name} {last_name}".strip()
	if full_name:
		return full_name
	if username:
		return username
	if email:
		return email
	return fallback


def _safe_strip(value) -> str:
	return str(value).strip() if value else ""


def _format_signature_entry(signature: Signature) -> str:
	signer = signature.signer
	full_name = signer.get_full_name().strip()
	if not full_name:
		full_name = signer.username or signer.email or str(signer.pk)
	role = signature.role or ''
	return f"[{full_name} | {role} | {_format_datetime(signature.date_signed)}]"


def _format_datetime(value) -> str:
	if not value:
		return ''
	try:
		value = timezone.localtime(value)
	except (ValueError, TypeError):
		pass
	return value.strftime('%Y-%m-%d %H:%M:%S')


def _ensure_download_dir(target_slug: str) -> str:
	download_dir = os.path.join(settings.MEDIA_ROOT, 'downloads', target_slug)
	os.makedirs(download_dir, exist_ok=True)
	return download_dir


def _build_media_download_url(request: Request, file_path: str) -> str:
	relative_path = os.path.relpath(file_path, settings.MEDIA_ROOT).replace(os.sep, '/')
	media_url = settings.MEDIA_URL or '/media/'
	if not media_url.endswith('/'):
		media_url = f"{media_url}/"
	if not media_url.startswith('/'):
		media_url = f"/{media_url}"
	return request.build_absolute_uri(f"{media_url}{relative_path}")



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


# Prefetch paths required by InvoiceSerializer / the brief GRN+PO serializers so
# every nested field resolves from cache instead of a per-row query. Shared by the
# hydrate path and the (summary-view) combined queryset to avoid drift.
_SIGNABLE_PREFETCH_PATHS = (
	'invoice_line_items',
	'invoice_line_items__po_line_item',
	# PO line item -> its GRN receipts, so the serializer's delivered_quantity
	# field resolves from cache instead of a per-item Sum aggregate.
	'invoice_line_items__po_line_item__grn_line_item',
	'invoice_line_items__grn_line_item',
	# GRN line item -> its invoice receipts, so invoiced_quantity / is_invoiced
	# on the brief serializer resolve from cache instead of a per-item aggregate.
	'invoice_line_items__grn_line_item__invoice_items',
	'grn__purchase_order__line_items',
	'grn__purchase_order__line_items__delivery_store',
	'grn__purchase_order__line_items__grn_line_item',
	# Prefetch GRN line items and their delivery stores to support GRN.stores property
	'grn__line_items',
	'grn__line_items__purchase_order_line_item__delivery_store',
	# Same as above, for PO line items reached via the GRN line item path
	# (GoodsReceivedLineItemBriefSerializer.get_purchase_order_line_item).
	'grn__line_items__purchase_order_line_item__grn_line_item',
	'grn__line_items__invoice_items',
)


def build_product_config_map(invoices: list) -> dict:
	"""
	Build a {product_id: conversion_field} lookup for every product referenced by
	the given invoices' line items, in a single query. Mirrors the bulk-load idiom
	in egrn_service.views and lets the serializer resolve `extra_fields` without a
	per-line-item ProductConfiguration query.

	Reads product IDs from prefetched relations (invoice_line_items ->
	po_line_item.metadata) so collecting the IDs costs no extra queries.
	"""
	from egrn_service.models import ProductConfiguration

	product_ids = set()
	for invoice in invoices:
		for li in invoice.invoice_line_items.all():
			po_li = li.po_line_item
			product_id = (getattr(po_li, 'metadata', None) or {}).get('ProductID')
			if product_id:
				product_ids.add(product_id)

	if not product_ids:
		return {}

	config_map = {}
	configs = ProductConfiguration.objects.filter(
		product_id__in=product_ids
	).select_related('conversion')
	for config in configs:
		conversion = config.conversion
		config_map[config.product_id] = conversion.conversion_field if conversion else []
	return config_map


def make_filtered_signable_queryset(signable_class: object, relevant_permissions: list) -> QuerySet:
	"""
	Light queryset for FILTERING and PAGINATION only: the signatory filter plus an
	ordering, with NO Sum() annotations, NO Exists, NO prefetch and NO .distinct().

	The heavy version (make_base_signable_queryset) wraps three SUM aggregates and a
	dependent Exists subquery in a GROUP BY + DISTINCT over six joined tables; MySQL
	then cannot apply the LIMIT until it has built and filesorted that entire grouped
	result. Measured at ~4.9s for a 15-row page. This light query is a single-table
	scan the LIMIT can short-circuit (~40ms). Pair it with hydrate_signables_by_ids:
	paginate cheaply here, then hydrate only the page's rows there.
	"""
	q_objects = [Q(signatories__contains=perm) for perm in relevant_permissions]
	query = reduce(operator.or_, q_objects)
	return signable_class.objects.filter(query)


def hydrate_signables_by_ids(signable_class: object, content_type: ContentType,
							 relevant_permissions: list, ids: list, order_by: str) -> list:
	"""
	Load FULL signable objects (serializer prefetches + user_has_signed Exists +
	gross/tax/net totals) for a specific, already-paginated set of ids. Totals are
	computed via a separate single-table aggregate and attached as *_annotated attrs,
	rather than annotated onto the row query (which would force the GROUP BY + DISTINCT
	+ filesort that made this slow). Returns a list ordered to match `order_by`
	(filter(id__in=...) does not preserve order).
	"""
	if not ids:
		return []
	# Lean hydrate query: select_related + prefetch only. NO Sum() annotations (they
	# force a LEFT JOIN invoice_line_items + GROUP BY across six tables, hence DISTINCT
	# + a temporary table + filesort; ~214ms even for 15 ids), NO .distinct() (rows are
	# fetched by unique primary key), and NO user_has_signed Exists (the list serializer
	# derives workflow state from the prefetched signatures map, and the "completed"
	# filter runs on the light queryset; nothing here reads the annotation). Totals are
	# computed in one cheap separate aggregate below.
	queryset = signable_class.objects.select_related(
		'purchase_order',
		'purchase_order__vendor',
		'grn',
		'grn__purchase_order',
		'grn__purchase_order__vendor',
	).prefetch_related(
		*_SIGNABLE_PREFETCH_PATHS
	).filter(id__in=ids)
	# Re-apply ordering: filter(id__in=...) does not guarantee row order, and the
	# caller already determined the correct page order on the light queryset.
	if order_by:
		queryset = queryset.order_by(order_by)

	objects = list(queryset)

	# Compute gross/tax/net totals for just these invoices in a single grouped
	# aggregate (single-table, indexed FK) and attach them under the same attribute
	# names the serializer and set_identity expect (gross_total_annotated, etc.).
	totals_by_id = {
		row['invoice']: row
		for row in InvoiceLineItem.objects.filter(invoice_id__in=ids).values('invoice').annotate(
			gross_total_annotated=Sum('gross_total'),
			total_tax_amount_annotated=Sum('tax_amount'),
			net_total_annotated=Sum('net_total'),
		)
	}
	for obj in objects:
		totals = totals_by_id.get(obj.id)
		obj.gross_total_annotated = totals['gross_total_annotated'] if totals else None
		obj.total_tax_amount_annotated = totals['total_tax_amount_annotated'] if totals else None
		obj.net_total_annotated = totals['net_total_annotated'] if totals else None

	return objects


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
			*_SIGNABLE_PREFETCH_PATHS
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