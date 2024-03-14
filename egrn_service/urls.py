from django.urls import path
from . import views

# Create your views here.
urlpatterns = [
	path('vendors/search', views.search_vendor),
	path('purchaseorders/<int:po_id>', views.get_order_items),
	path('purchaseorders/<int:po_id>/grns', views.get_order_with_grns),
	path('grn', views.create_grn),
	path('grn/<int:grn_number>', views.get_grn),
	path('grns', views.get_all_grns),
]
