from decimal import Decimal
from django.test import TestCase
from django.db import models
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from core_service.models import CustomUser, VendorProfile
from egrn_service.views import weighted_average

from .models import (
	GoodsReceivedNote, GoodsReceivedLineItem,
	PurchaseOrder, PurchaseOrderLineItem,
	StockConsumptionRecord, Store
)


class WeightedAverageConsumptionTest(TestCase):

	def setUp(self):
		self.user = CustomUser.objects.create_user(
			username="wacstest",
			email="wacstest@example.com",
			password="TestPass123"
		)
		self.vendor_profile = VendorProfile.objects.create(
			user=self.user,
			byd_internal_id="VEND-001",
			byd_metadata={}
		)
		self.store = Store.objects.create(
			store_name="Main Warehouse",
			store_email="warehouse@example.com",
			icg_warehouse_name="ICG Main",
			icg_warehouse_code="ICG-0001",
			byd_cost_center_code="4100003-17",
			metadata={}
		)
		self.purchase_order = PurchaseOrder.objects.create(
			vendor=self.vendor_profile,
			object_id="PO-0001",
			po_id=100,
			total_net_amount=Decimal('250'),
			date=timezone.now(),
			metadata={}
		)
		line_item = PurchaseOrderLineItem(
			purchase_order=self.purchase_order,
			delivery_store=self.store,
			object_id="POLI-1",
			product_id="PROD-A",
			product_name="Product A",
			quantity=Decimal('5'),
			unit_price=Decimal('50'),
			unit_of_measurement="KGM",
			metadata={"ProductID": "PROD-A", "QuantityUnitCode": "KGM"}
		)
		models.Model.save(line_item)

		grn = GoodsReceivedNote(
			purchase_order=self.purchase_order,
			grn_number=1234
		)
		models.Model.save(grn)

		GoodsReceivedLineItem.objects.create(
			grn=grn,
			purchase_order_line_item=line_item,
			quantity_received=Decimal('5'),
			net_value_received=Decimal('250'),
			gross_value_received=Decimal('250'),
			metadata={"ProductID": "PROD-A", "QuantityUnitCode": "KGM"}
		)

		StockConsumptionRecord.objects.create(
			product_id="PROD-A",
			product_name="Product A",
			quantity=Decimal('1'),
			unit_cost=Decimal('70'),
			unit_of_measurement="KGM",
			cost_center=self.store.byd_cost_center_code,
			metadata={"reason": "WAC test"}
		)

		self.factory = APIRequestFactory()

	def test_consumption_adjusts_weighted_average(self):
		request = self.factory.get("/api/v1/weighted-average", {"product_id": "PROD-A"})
		request.user = self.user

		response = weighted_average(request)
		self.assertEqual(response.status_code, 200)
		result = response.data["data"]["results"][0]
		self.assertAlmostEqual(result["wac"], 45.0, places=2)
		events = [entry["event"] for entry in result["history"]]
		self.assertIn("consumption", events)

# Create your tests here.
