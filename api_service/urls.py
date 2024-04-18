from django.urls import path, include
from .views import *
from core_service.views import CustomTokenObtainPairView

urlpatterns = [
	# Profile endpoints
	path('vendor/onboard/<str:action>', NewUserView.as_view(), name='onboarding'),
	path('vendor/authenticate', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
	path('vendor/profile', VendorProfileView.as_view(), name='vendor_profile'),
	# Purchase Order endpoints
	path('vendor/purchaseorders', get_vendors_orders, name="get_purchase_orders"),
	path('vendor/purchaseorders/<int:po_id>', get_vendors_orders, name="get_purchase_order"),
	# Invoice endpoints
	path('vendor/invoices', VendorInvoiceView.as_view(), name='vendor_invoice'),
	# Misc endpoints
	path('surcharges', get_surcharges, name='get_surcharges'),
]