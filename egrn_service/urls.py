from django.urls import path, include
from . import views


# Create your views here.
urlpatterns = [
	path('vendors/search', views.search_vendor),
	path('vendors/<int:vendor_id>/purchaseorders', views.get_vendors_orders),
	path('vendors/<int:vendor_id>/purchaseorders/<str:po_id>', views.get_order_items),
]