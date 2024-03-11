from django.urls import path
from . import views

# Create your views here.
urlpatterns = [
	path('vendors/search', views.search_vendor),
	path('vendors/<str:vendor_id>/purchaseorders', views.get_vendors_orders),
	path('vendors/<str:vendor_id>/purchaseorders/<str:po_id>', views.get_order_items),
]
