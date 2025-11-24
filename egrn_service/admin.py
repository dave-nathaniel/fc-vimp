from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
import logging
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin
from unfold.sites import UnfoldAdminSite
import pandas as pd
from django.db import models
import random
import string
from datetime import datetime
from copy import deepcopy
from decimal import Decimal
import uuid
from django_q.tasks import async_task
from .models import (
	PurchaseOrder, PurchaseOrderLineItem, GoodsReceivedNote,
	GoodsReceivedLineItem, StockConsumptionRecord
)
from byd_service.rest import RESTServices
from django.contrib.auth.decorators import user_passes_test
from django.contrib.admin.views.decorators import staff_member_required


def _get_latest_unit_price(product_id):
	try:
		line_item = PurchaseOrderLineItem.objects.filter(product_id=product_id).order_by('-id').first()
		return float(line_item.unit_price) if line_item else 0.0
	except Exception:
		return 0.0


class PurchaseOrderAdmin(ModelAdmin):
	# Search fields: vendor, object_id, po_id
	search_fields = [
		'vendor__user__first_name',
		'vendor__user__email',
		'vendor__byd_internal_id',
		'object_id',
		'po_id',
		'line_items__product_id',
		'line_items__product_name',
		'line_items__delivery_store__store_name',
        'line_items__delivery_store__store_email',
        'line_items__delivery_store__icg_warehouse_name',
        'line_items__delivery_store__icg_warehouse_code',
        'line_items__delivery_store__byd_cost_center_code',
		
	]


class PurchaseOrderLineItemAdmin(ModelAdmin):
	# Search fields: purchase_order, delivery_store, object_id, product_id, product_name
	search_fields = [
		'purchase_order__po_id',
		'purchase_order__vendor__user__first_name',
		'purchase_order__vendor__user__email',
		'purchase_order__vendor__byd_internal_id',
		'delivery_store__store_name',
		'delivery_store__store_email',
		'delivery_store__icg_warehouse_name',
		'delivery_store__icg_warehouse_code',
		'delivery_store__byd_cost_center_code',
		'object_id',
		'product_id',
		'product_name',
	]


byd_rest_services = RESTServices()


class GoodsReceivedNoteAdmin(ModelAdmin):
	# Search fields: grn_number
	search_fields = [
		'grn_number',
		'purchase_order__vendor__user__first_name',
		'purchase_order__vendor__user__email',
		'purchase_order__vendor__byd_internal_id',
		'purchase_order__po_id'
	]
	actions = ['nullify_grn']

	def _build_cancel_payload(self, grn):
		payload = grn.inbound_delivery_metadata.get('payload')
		if not payload:
			raise ValueError("Inbound delivery payload not available.")

		cancel_payload = deepcopy(payload)
		notification_id = grn.inbound_delivery_notification_id or str(grn.grn_number)
		cancel_payload["ID"] = f"{notification_id}-CAN-{uuid.uuid4().hex[:4].upper()}"
		cancel_payload["Item"] = []

		for item in payload["Item"]:
			cancel_item = deepcopy(item)
			quantity = Decimal(cancel_item["ItemDeliveryQuantity"]["Quantity"])
			cancel_item["ItemDeliveryQuantity"]["Quantity"] = str(-abs(quantity))
			if "QuantityTypeCode" not in cancel_item["ItemDeliveryQuantity"]:
				cancel_item["ItemDeliveryQuantity"]["QuantityTypeCode"] = cancel_item["ItemDeliveryQuantity"].get("UnitCode")
			if cancel_item.get("ItemInboundDeliveryRequestReference"):
				cancel_item["ItemInboundDeliveryRequestReference"]["ID"] = cancel_payload["ID"]
			cancel_payload["Item"].append(cancel_item)

		if "ItemInboundDeliveryRequestReference" in cancel_payload:
			cancel_payload["ItemInboundDeliveryRequestReference"]["ID"] = cancel_payload["ID"]
		return cancel_payload

	def nullify_grn(self, request, queryset):
		success_count = 0
		error_messages = []
		for grn in queryset:
			if grn.is_nullified:
				error_messages.append(f"GRN {grn.grn_number} already nullified.")
				continue
			try:
				cancel_payload = self._build_cancel_payload(grn)
				async_task(
					'vimp.tasks.cancel_inbound_delivery_notification_on_byd',
					grn.id,
					cancel_payload,
					q_options={
						'task_name': f'Cancel-Inbound-Notif-{grn.grn_number}-ByD'
					}
				)
				grn.inbound_delivery_metadata.setdefault("nullifications_pending", []).append({
					"payload": cancel_payload,
					"queued_at": datetime.utcnow().isoformat(),
				})
				grn.save(update_fields=['inbound_delivery_metadata'])
				success_count += 1
			except Exception as exc:
				error_messages.append(f"GRN {grn.grn_number}: {exc}")

		if success_count:
			self.message_user(request, f"{success_count} GRN(s) cancellation queued.", level=messages.SUCCESS)
		for msg in error_messages:
			self.message_user(request, msg, level=messages.ERROR)

	nullify_grn.short_description = "Nullify selected GRNs in ByD"


class GoodsReceivedLineItemAdmin(ModelAdmin):
	# Search fields: grn, purchase_order_line_item, object_id, product_id, product_name
	search_fields = [
		'grn__grn_number',
		'purchase_order_line_item__purchase_order__po_id',
		'purchase_order_line_item__delivery_store__store_name',
		'purchase_order_line_item__delivery_store__store_email',
		'purchase_order_line_item__delivery_store__icg_warehouse_name',
		'purchase_order_line_item__delivery_store__icg_warehouse_code',
		'purchase_order_line_item__delivery_store__byd_cost_center_code',
		'purchase_order_line_item__purchase_order__vendor__user__first_name',
		'purchase_order_line_item__purchase_order__vendor__user__email',
		'purchase_order_line_item__purchase_order__vendor__byd_internal_id',
		'purchase_order_line_item__product_name',
		'purchase_order_line_item__object_id',
		'purchase_order_line_item__product_id',
	]


admin.site.register(PurchaseOrder, PurchaseOrderAdmin)
admin.site.register(PurchaseOrderLineItem, PurchaseOrderLineItemAdmin)
admin.site.register(GoodsReceivedNote, GoodsReceivedNoteAdmin)
admin.site.register(GoodsReceivedLineItem, GoodsReceivedLineItemAdmin)


@staff_member_required
def bulk_inventory_update_view(request):
	if request.method == 'POST':
		return process_bulk_inventory_update(request)
	return render(request, 'admin/bulk_inventory_update.html', {
		'title': 'Bulk Inventory Update',
		'opts': GoodsReceivedLineItem._meta,
		'is_popup': False,
		'is_nav_sidebar_enabled': False,
		'has_permission': True,
		'show_back_button': True,
	})

@staff_member_required
def process_bulk_inventory_update(request):
	try:
		# Get form data
		external_id = request.POST.get('external_id', '').strip()
		site_id = request.POST.get('site_id', '').strip()
		cost_center_id = request.POST.get('cost_center_id', '').strip()
		transaction_datetime = request.POST.get('transaction_datetime', '').strip()
		
		# Validate required fields
		if not site_id:
			return JsonResponse({'success': False, 'error': 'Site ID is required'})
		
		# Generate external ID if not provided
		if not external_id:
			external_id = generate_external_id()
		
		# Default cost center to site ID if not provided
		if not cost_center_id:
			cost_center_id = site_id
		
		# Format datetime if not provided
		if not transaction_datetime:
			transaction_datetime = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
		
		# Process uploaded file
		if 'excel_file' not in request.FILES:
			return JsonResponse({'success': False, 'error': 'No file uploaded'})
		
		file = request.FILES['excel_file']
		
		# Read Excel file
		try:
			if file.name.endswith('.csv'):
				df = pd.read_csv(file)
			else:
				df = pd.read_excel(file)
		except Exception as e:
			return JsonResponse({'success': False, 'error': f'Error reading file: {str(e)}'})
		
		# Validate required columns
		required_columns = ['external_item_id', 'material_internal_id', 'owner_party_internal_id', 
							'inventory_restricted_use_indicator', 'logistics_area_id', 'quantity', 'unit_code']
		missing_columns = [col for col in required_columns if col not in df.columns]
		
		if missing_columns:
			return JsonResponse({'success': False, 'error': f'Missing required columns: {", ".join(missing_columns)}'})
		
		# Process inventory items
		inventory_items = []
		consumption_records = []
		for _, row in df.iterrows():
			try:
				from byd_service.goods_issue import format_inventory_item
				
				item = format_inventory_item(
					external_item_id=str(row['external_item_id']),
					material_internal_id=str(row['material_internal_id']),
					owner_party_internal_id=str(row['owner_party_internal_id']),
					inventory_restricted_use_indicator=bool(row['inventory_restricted_use_indicator']),
					logistics_area_id=str(row['logistics_area_id']),
					quantity=float(row['quantity']),
					unit_code=str(row['unit_code']),
				)
				inventory_items.append(item)
				consumption_records.append({
					"product_id": str(row['material_internal_id']),
					"product_name": row.get('product_name') or "",
					"quantity": float(row['quantity']),
					"unit_cost": _get_latest_unit_price(str(row['material_internal_id'])),
					"unit_of_measurement": str(row['unit_code']),
					"cost_center": cost_center_id,
					"external_item_id": str(row['external_item_id']),
					"metadata": row.to_dict(),
				})
			except Exception as e:
				return JsonResponse({'success': False, 'error': f'Error processing row {len(inventory_items) + 1}: {str(e)}'})
		
		# Call goods issue service
		try:
			from byd_service.goods_issue import post_goods_consumption_for_cost_center
			
			request_data = {
				"external_id": external_id,
				"site_id": site_id,
				"inventory_movement_direction_code": "1",
				"inventory_items": inventory_items,
				"transaction_datetime": transaction_datetime,
				"cost_center_id": cost_center_id
			}

			success = post_goods_consumption_for_cost_center(**request_data)
			
			if success:
				for record in consumption_records:
					try:
						StockConsumptionRecord.objects.create(
							product_id=record["product_id"],
							product_name=record["product_name"],
							quantity=record["quantity"],
							unit_cost=record["unit_cost"],
							unit_of_measurement=record["unit_of_measurement"],
							cost_center=record["cost_center"],
							external_item_id=record["external_item_id"],
							metadata=record["metadata"],
						)
					except Exception as e:
						logging.error(f"Failed to persist stock consumption record: {e}")
				messages.success(request, f'Successfully processed {len(inventory_items)} inventory items')
				return JsonResponse({'success': True, 'message': f'Successfully processed {len(inventory_items)} inventory items'})
			else:
				return JsonResponse({'success': False, 'error': 'Failed to post inventory updates to SAP'})
				
		except Exception as e:
			return JsonResponse({'success': False, 'error': f'Error calling goods issue service: {str(e)}'})
	
	except Exception as e:
		return JsonResponse({'success': False, 'error': f'Unexpected error: {str(e)}'})

def generate_external_id():
	"""Generate a 7-character random ID"""
	return ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))

@staff_member_required
def download_sample_csv(request):
	"""Download sample CSV file"""
	sample_data = {
		'external_item_id': ['ITEM001', 'ITEM002', 'ITEM003'],
		'material_internal_id': ['RM1000072', 'RM1000073', 'RM1000074'],
		'owner_party_internal_id': ['FC-0001', 'FC-0001', 'FC-0001'],
		'inventory_restricted_use_indicator': [False, False, True],
		'logistics_area_id': ['4100003-17', '4100003-17', '4100003-17'],
		'quantity': [1.0, 2.5, 3.0],
		'unit_code': ['KGM', 'PCE', 'LTR'],
		'inventory_stock_status_code': ['', '1', '2'],
		'identified_stock_id': ['', '', 'STOCK001']
	}
	
	df = pd.DataFrame(sample_data)
	
	response = HttpResponse(content_type='text/csv')
	response['Content-Disposition'] = 'attachment; filename="inventory_update_sample.csv"'
	
	df.to_csv(response, index=False)
	return response


class InventoryTools(ModelAdmin):

	_meta = GoodsReceivedLineItem._meta
	_meta.name = 'Inventory Tools'
	_default_manager = GoodsReceivedLineItem.objects
	
	def get_urls(self):
		"""
			Adds custom urls to the admin site.
		"""
		custom_urls =  [
			path('', self.admin_site.admin_view(bulk_inventory_update_view), name='bulk_inventory_update'),
			path('bulk-inventory-update/', self.admin_site.admin_view(bulk_inventory_update_view), name='bulk_inventory_update'),
			path('download-sample-csv/', self.admin_site.admin_view(download_sample_csv), name='download_sample_csv'),
		] + super().get_urls()

		return custom_urls

inventory_tools = InventoryTools(model=InventoryTools, admin_site=admin.site)