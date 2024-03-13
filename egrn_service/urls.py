from django.urls import path
from . import views

# Create your views here.
urlpatterns = [
	path('vendors/search', views.search_vendor),
	path('purchaseorders/<int:po_id>', views.get_order_items),
	path('grn', views.create_grn),
]
