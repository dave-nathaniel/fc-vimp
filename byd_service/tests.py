# Import necessary modules for testing
from django.test import TestCase
from django.urls import reverse
from .rest import RESTServices

# Define your test case class
class RESTServicesTest(TestCase):

	def setUp(self):
		self.main_model = RESTServices()

	def test_get_vendor_by_id(self):
		results = self.main_model.get_vendor_by_id('07033245515', "phone")
		
		# Assert that the response status code is 200 (OK)
		self.assertEqual(type(results), dict)

	# Define teardown method if needed
	def tearDown(self):
		pass