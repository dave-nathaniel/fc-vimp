import os
from decimal import Decimal
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from approval_service.models import Signature
from approval_service.views import download_signables_excel_view
from core_service.models import CustomUser, VendorProfile
from egrn_service.models import (
	PurchaseOrder,
	PurchaseOrderLineItem,
	GoodsReceivedNote,
	GoodsReceivedLineItem,
	Store,
)
from invoice_service.models import Invoice, InvoiceLineItem


@override_settings(
	CACHES={
		'default': {
			'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
			'LOCATION': 'approval-service-tests',
		}
	},
	CACHALOT_ENABLED=False,
)
class DownloadSignablesExcelViewTests(TestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.user = CustomUser.objects.create_user(
			username='approver',
			email='approver@example.com',
			password='password123',
			first_name='Alice',
			last_name='Approver',
		)
		permission = Permission.objects.get(
			codename='accounts_payable',
			content_type__app_label='invoice_service'
		)
		self.user.user_permissions.add(permission)

		vendor_user = CustomUser.objects.create_user(
			username='vendor',
			email='vendor@example.com',
			password='password123',
			first_name='Vendor',
			last_name='One',
		)
		self.vendor_profile = VendorProfile.objects.create(
			user=vendor_user,
			byd_internal_id='BYD-001'
		)

		self.store = Store.objects.create(
			store_name='Test Store',
			store_email='store@example.com',
			icg_warehouse_code='WH-001',
			byd_cost_center_code='COST-001',
		)

		self.purchase_order = PurchaseOrder.objects.create(
			vendor=self.vendor_profile,
			object_id='PO-OBJ-1',
			po_id=1001,
			total_net_amount=Decimal('5000.00'),
			date=timezone.now().date(),
			metadata={}
		)

		self.po_line_item = PurchaseOrderLineItem.objects.create(
			purchase_order=self.purchase_order,
			delivery_store=self.store,
			object_id='LINE-001',
			product_id='PROD-001',
			product_name='Sample Item',
			quantity=Decimal('10'),
			unit_price=Decimal('100'),
			unit_of_measurement='EA',
			metadata={
				'NetAmount': '1000',
				'TaxAmount': '50',
				'ItemShipToLocation': {
					'LocationID': self.store.byd_cost_center_code,
				},
				'ProductID': 'PROD-001',
			}
		)

		self.goods_received_note = GoodsReceivedNote.objects.create(
			purchase_order=self.purchase_order,
			grn_number=2001,
		)

		self.grn_line_item = GoodsReceivedLineItem(
			grn=self.goods_received_note,
			purchase_order_line_item=self.po_line_item,
			quantity_received=Decimal('5'),
			metadata={}
		)
		self.grn_line_item.save(data={'extra_fields': {}})

		self.invoice = Invoice.objects.create(
			purchase_order=self.purchase_order,
			grn=self.goods_received_note,
			due_date=timezone.now().date(),
			payment_reason='Test Payment',
			signatories=['accounts_payable'],
			current_pending_signatory='accounts_payable',
		)

		self.invoice_line_item = InvoiceLineItem(
			invoice=self.invoice,
			po_line_item=self.po_line_item,
			grn_line_item=self.grn_line_item,
		)
		self.invoice_line_item.save()

		content_type = ContentType.objects.get_for_model(Invoice)
		Signature.objects.create(
			signer=self.user,
			signature='signed-token',
			accepted=True,
			comment='Looks good',
			signable_type=content_type,
			signable_id=self.invoice.id,
			metadata={"acting_as": "accounts_payable"}
		)

	def test_download_endpoint_generates_file_and_link(self):
		with TemporaryDirectory() as tmp_dir, override_settings(MEDIA_ROOT=tmp_dir):
			request = self.factory.get('/approval/download/invoice')
			force_authenticate(request, user=self.user)
			response = download_signables_excel_view(request, 'invoice')

			self.assertEqual(response.status_code, status.HTTP_200_OK)

			response_data = response.data.get('data', {})
			self.assertEqual(response_data.get('row_count'), 1)
			download_url = response_data.get('download_url')
			self.assertIsNotNone(download_url)

			parsed = urlparse(download_url)
			media_prefix = '/' + (settings.MEDIA_URL or 'media/').lstrip('/')
			self.assertTrue(parsed.path.startswith(media_prefix))

			relative_path = parsed.path[len(media_prefix):]
			file_path = os.path.join(tmp_dir, relative_path.replace('/', os.sep))
			self.assertTrue(os.path.exists(file_path))
