from django.urls import path, include
from .views import NewUserView, CustomTokenObtainPairView, get_vendors_orders, create_invoice

urlpatterns = [
	path('vendor/onboard/<str:action>', NewUserView.as_view(), name='onboarding'),
	path('vendor/authenticate', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
	path('vendor/purchaseorders', get_vendors_orders, name="get_invoicable_purchase_orders"),
	path('vendor/purchaseorders/<int:po_id>', get_vendors_orders, name="get_purchase_order"),
	path('vendor/invoice', create_invoice, name='create_invoice'),
]