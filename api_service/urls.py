from django.urls import path, include
from .views import *
from invoice_service.views import *
from approval_service.views import *
from core_service.views import login_user, verify_otp
from egrn_service.views import get_vendors_grns

urlpatterns = [
	# Profile endpoints
	path('vendor/onboard/<str:action>', NewUserView.as_view(), name='onboarding'),
	path('vendor/authenticate', login_user, name='get_otp'),
	path('vendor/verify-otp', verify_otp, name='verify_otp'),
	path('vendor/profile', VendorProfileView.as_view(), name='vendor_profile'),
	# Purchase Order endpoints
	path('vendor/purchaseorders', get_vendors_orders, name="get_purchase_orders"),
	path('vendor/purchaseorders/<int:po_id>', get_vendors_orders, name="get_purchase_order"),
	#GRN endpoints
	path('vendor/grns', get_vendors_grns, name="get_vendors_grns"),
	# Invoice endpoints
	path('vendor/invoices', VendorInvoiceView.as_view(), name='vendor_invoice'),
	# Misc endpoints
	path('surcharges', get_surcharges, name='get_surcharges'),
	
	# Approval endpoints
	path('approvals/createkey', KeystoreAPIView.as_view(), name='manage_keystore'),
]