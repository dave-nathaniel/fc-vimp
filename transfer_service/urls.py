from django.urls import path
from . import views

urlpatterns = [
    # Delivery management endpoints (primary workflow)
    path('deliveries/', views.get_inbound_deliveries, name='delivery-list'),
    path('deliveries/<str:pk>/', views.get_inbound_delivery, name='delivery-detail'),
    path('deliveries/search/', views.search_deliveries, name='search-deliveries'),
    path('deliveries/receive', views.create_delivery_receipt, name='create-delivery-receipt'),
]