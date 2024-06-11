from django.urls import path
from . import views

# Create your views here.
urlpatterns = [
	path('vendors/search', views.search_vendor),
	path('purchaseorders/<int:po_id>', views.get_purchase_order),
	path('purchaseorders/<int:po_id>/grns', views.get_purchase_order),
	path('grn', views.create_grn),
	path('grn/<int:grn_number>', views.get_grn),
	path('grns', views.get_all_grns),
	path('wac', views.weighted_average),
]
