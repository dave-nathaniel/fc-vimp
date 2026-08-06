"""
Tests for the ByD posting idempotency/resume fixes.

The duplicate-posting defect: the create+post tasks retried the WHOLE function
after a failure, so a failure on the post step (typically a ByD object lock,
which fires routinely on a freshly created document) re-ran the create step and
committed a second document in ByD. Random external IDs meant ByD could not
recognise the re-send as a duplicate, and each attempt overwrote the previous
attempt's ObjectID locally, hiding the evidence.

These tests pin the fixed behaviour:
  - external IDs are deterministic per GRN,
  - a retry after a failed post RESUMES at the post step (no second create),
  - stranded documents (created in ByD, never recorded locally) are recovered
    by lookup instead of re-created,
  - completed postings short-circuit re-entry (stale retries, admin re-dispatch,
    broker re-delivery),
  - the posting-status row is one-per-(object, task) and its retry counter is
    concurrency-safe,
  - the per-PO mutex only ever releases a lock it still owns.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import models, transaction
from django.db.utils import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone

from django_q.models import Schedule

from byd_service import util as byd_util
from byd_service.models import ByDPostingStatus, get_or_create_byd_posting_status
from core_service.models import CustomUser, VendorProfile
from egrn_service.models import (
	GoodsReceivedLineItem, GoodsReceivedNote, PurchaseOrder,
	PurchaseOrderLineItem, Store,
)
from vimp import tasks

NOTIF_TASK = 'vimp.tasks.create_inbound_delivery_notification_on_byd'
GRN_TASK = 'vimp.tasks.create_grn_on_byd'

LOCMEM_CACHES = {
	'default': {
		'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
		'LOCATION': 'byd-idempotency-tests',
	}
}


def build_grn(grn_number=1488871, po_id=148887, username="byd_test_vendor"):
	"""
		Minimal PO -> line item -> GRN graph carrying the ByD metadata keys the
		posting payload builders read. Saved via models.Model.save / plain field
		saves so none of the async side effects in the custom save() methods fire.
	"""
	user = CustomUser.objects.create_user(
		username=username,
		email=f"{username}@example.com",
		password="TestPass123",
	)
	vendor = VendorProfile.objects.create(
		user=user, byd_internal_id="S1001179", byd_metadata={}
	)
	store = Store.objects.create(
		store_name="Test Store",
		store_email="store@example.com",
		icg_warehouse_name="ICG Test",
		icg_warehouse_code=f"ICG-{grn_number}",
		byd_cost_center_code=f"CC-{grn_number}",
		metadata={},
	)
	po = PurchaseOrder.objects.create(
		vendor=vendor,
		object_id=f"PO-OBJ-{po_id}",
		po_id=po_id,
		total_net_amount=Decimal('100'),
		date=timezone.now().date(),
		metadata={},
	)
	line_item = PurchaseOrderLineItem(
		purchase_order=po,
		delivery_store=store,
		object_id=f"POLI-OBJ-{po_id}",
		product_id="PROD-1",
		product_name="Product 1",
		quantity=Decimal('10'),
		unit_price=Decimal('10'),
		unit_of_measurement="EA",
		metadata={
			"ProductID": "PROD-1",
			"QuantityUnitCode": "EA",
			"ID": "10",
			"ItemTypeCode": "18",
			"NetAmount": "100",
			"TaxAmount": "0",
		},
	)
	models.Model.save(line_item)

	grn = GoodsReceivedNote(purchase_order=po, grn_number=grn_number)
	models.Model.save(grn)

	GoodsReceivedLineItem.objects.create(
		grn=grn,
		purchase_order_line_item=line_item,
		quantity_received=Decimal('5'),
		net_value_received=Decimal('50'),
		gross_value_received=Decimal('50'),
		metadata={},
	)
	return grn


def mock_rest_client():
	"""
		A RESTServices stand-in with happy-path defaults. The lookup MUST default
		to None (a bare MagicMock is truthy and would read as 'document found').
	"""
	client = MagicMock()
	client.get_inbound_delivery_by_external_id.return_value = None
	client.create_inbound_delivery_notification.return_value = {
		"d": {"results": {"ObjectID": "BYD-OID-1"}}
	}
	client.post_delivery_notification.return_value = {"posted": True}
	client.create_grn.return_value = {"d": {"results": {"ObjectID": "BYD-GSA-1"}}}
	client.post_grn.return_value = {"released": True}
	return client


@override_settings(CACHES=LOCMEM_CACHES)
class NotificationTaskIdempotencyTests(TestCase):

	def setUp(self):
		cache.clear()
		self.grn = build_grn()
		self.client_mock = mock_rest_client()
		self._patches = [
			patch('vimp.tasks.byd_rest.RESTServices', return_value=self.client_mock),
			patch('vimp.tasks.time.sleep', lambda *_: None),
		]
		for p in self._patches:
			p.start()
			self.addCleanup(p.stop)

	def _status(self):
		return get_or_create_byd_posting_status(self.grn, task_name=NOTIF_TASK)

	def test_notification_id_is_deterministic(self):
		result = tasks.create_inbound_delivery_notification_on_byd(self.grn)
		self.assertTrue(result)
		self.grn.refresh_from_db()
		self.assertEqual(self.grn.inbound_delivery_notification_id, str(self.grn.grn_number))
		self.assertEqual(self.grn.inbound_delivery_object_id, "BYD-OID-1")
		payload = self.client_mock.create_inbound_delivery_notification.call_args[0][0]
		self.assertEqual(payload["ID"], str(self.grn.grn_number))
		self.assertEqual(self._status().status, 'success')

	def test_retry_after_post_failure_resumes_without_recreating(self):
		# Attempt 1: create succeeds, post hits a ByD object lock.
		self.client_mock.post_delivery_notification.side_effect = Exception("Object is locked")
		result = tasks.create_inbound_delivery_notification_on_byd(self.grn)
		self.assertFalse(result)

		self.grn.refresh_from_db()
		# The created document's identity was persisted BEFORE the post step...
		self.assertEqual(self.grn.inbound_delivery_object_id, "BYD-OID-1")
		status = self._status()
		self.assertEqual(status.status, 'failed')
		self.assertEqual(status.retry_count, 1)
		# ...and a backoff retry was scheduled for the lock conflict.
		self.assertEqual(Schedule.objects.filter(func=NOTIF_TASK).count(), 1)

		# Attempt 2 (as the scheduled retry would run it: by id, lock cleared).
		self.client_mock.post_delivery_notification.side_effect = None
		result = tasks.create_inbound_delivery_notification_on_byd(self.grn.id)
		self.assertTrue(result)

		# THE regression assertion: exactly ONE document was ever created.
		self.client_mock.create_inbound_delivery_notification.assert_called_once()
		self.assertEqual(self.client_mock.post_delivery_notification.call_count, 2)
		self.assertEqual(self._status().status, 'success')

	def test_success_guard_short_circuits_reentry(self):
		status = self._status()
		status.mark_success({"ObjectID": "BYD-OID-1", "ID": str(self.grn.grn_number)})

		result = tasks.create_inbound_delivery_notification_on_byd(self.grn)
		self.assertTrue(result)
		self.client_mock.create_inbound_delivery_notification.assert_not_called()
		self.client_mock.post_delivery_notification.assert_not_called()

	def test_stranded_document_recovered_by_lookup(self):
		# A previous attempt created the document in ByD but died before
		# recording anything locally. The lookup finds it by deterministic ID.
		self.client_mock.get_inbound_delivery_by_external_id.return_value = {
			"ObjectID": "BYD-OID-9", "ReleaseStatusCode": "1",
		}
		result = tasks.create_inbound_delivery_notification_on_byd(self.grn)
		self.assertTrue(result)
		self.client_mock.create_inbound_delivery_notification.assert_not_called()
		self.client_mock.post_delivery_notification.assert_called_once_with("BYD-OID-9")
		self.grn.refresh_from_db()
		self.assertEqual(self.grn.inbound_delivery_object_id, "BYD-OID-9")

	def test_released_document_is_not_posted_again(self):
		# The stranded document was already posted (Released) as well.
		self.client_mock.get_inbound_delivery_by_external_id.return_value = {
			"ObjectID": "BYD-OID-9", "ReleaseStatusCode": "3",
		}
		result = tasks.create_inbound_delivery_notification_on_byd(self.grn)
		self.assertTrue(result)
		self.client_mock.create_inbound_delivery_notification.assert_not_called()
		self.client_mock.post_delivery_notification.assert_not_called()
		self.assertEqual(self._status().status, 'success')

	def test_nullified_grn_is_not_posted(self):
		GoodsReceivedNote.objects.filter(pk=self.grn.pk).update(is_nullified=True)
		self.grn.refresh_from_db()
		result = tasks.create_inbound_delivery_notification_on_byd(self.grn)
		self.assertFalse(result)
		self.client_mock.create_inbound_delivery_notification.assert_not_called()
		self.client_mock.post_delivery_notification.assert_not_called()


@override_settings(CACHES=LOCMEM_CACHES)
class GRNTaskResumeTests(TestCase):

	def setUp(self):
		cache.clear()
		self.grn = build_grn(grn_number=1435271, po_id=143527, username="byd_gsa_vendor")
		self.client_mock = mock_rest_client()
		self._patches = [
			patch('vimp.tasks.byd_rest.RESTServices', return_value=self.client_mock),
			patch('vimp.tasks.time.sleep', lambda *_: None),
		]
		for p in self._patches:
			p.start()
			self.addCleanup(p.stop)

	def test_resumes_from_status_row_after_post_failure(self):
		self.client_mock.post_grn.side_effect = Exception("Object is locked")
		self.assertFalse(tasks.create_grn_on_byd(self.grn))

		status = get_or_create_byd_posting_status(self.grn, task_name=GRN_TASK)
		# The created document's ObjectID survived the failure on the status row.
		self.assertEqual(status.status, 'failed')
		self.assertEqual((status.response_data or {}).get("ObjectID"), "BYD-GSA-1")

		self.client_mock.post_grn.side_effect = None
		self.assertTrue(tasks.create_grn_on_byd(self.grn.id))

		self.client_mock.create_grn.assert_called_once()
		status.refresh_from_db()
		self.assertEqual(status.status, 'success')


class PostingStatusModelTests(TestCase):

	def setUp(self):
		self.grn = build_grn(grn_number=1442931, po_id=144293, username="byd_status_vendor")

	def test_increment_retry_is_concurrency_safe(self):
		row_a = get_or_create_byd_posting_status(self.grn, task_name=NOTIF_TASK)
		row_b = ByDPostingStatus.objects.get(pk=row_a.pk)
		# Two workers holding the same row both increment; with a plain
		# read-modify-write both would write 1 and fork the retry chain.
		row_a.increment_retry()
		row_b.increment_retry()
		row_a.refresh_from_db()
		self.assertEqual(row_a.retry_count, 2)

	def test_one_status_row_per_object_and_task(self):
		first = get_or_create_byd_posting_status(self.grn, task_name=NOTIF_TASK)
		second = get_or_create_byd_posting_status(self.grn, task_name=NOTIF_TASK)
		self.assertEqual(first.pk, second.pk)

		content_type = first.content_type
		with self.assertRaises(IntegrityError):
			with transaction.atomic():
				ByDPostingStatus.objects.create(
					content_type=content_type,
					object_id=self.grn.id,
					django_q_task_name=NOTIF_TASK,
				)

	def test_mark_failure_preserves_resume_object_id(self):
		status = get_or_create_byd_posting_status(self.grn, task_name=GRN_TASK)
		status.response_data = {"ObjectID": "BYD-GSA-1", "stage": "created"}
		status.save(update_fields=['response_data'])

		status.mark_failure("Object is locked")
		status.refresh_from_db()
		self.assertEqual(status.status, 'failed')
		# The resume pointer must survive the failure bookkeeping.
		self.assertEqual((status.response_data or {}).get("ObjectID"), "BYD-GSA-1")


@override_settings(CACHES=LOCMEM_CACHES)
class PoWriteLockTests(TestCase):

	def setUp(self):
		cache.clear()

	def test_mutual_exclusion_and_release(self):
		with byd_util.po_write_lock(42) as outer:
			self.assertTrue(outer)
			with byd_util.po_write_lock(42) as inner:
				self.assertFalse(inner)
		# Released on exit: can be acquired again.
		with byd_util.po_write_lock(42) as again:
			self.assertTrue(again)

	def test_release_does_not_delete_another_workers_lock(self):
		key = f"{byd_util.PO_LOCK_PREFIX}:77"
		lock_cm = byd_util.po_write_lock(77)
		self.assertTrue(lock_cm.__enter__())
		# Simulate this worker's lock expiring and another worker acquiring it.
		cache.delete(key)
		cache.add(key, "another-workers-token", 60)
		lock_cm.__exit__(None, None, None)
		# The other worker's lock must still be there.
		self.assertEqual(cache.get(key), "another-workers-token")
