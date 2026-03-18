from django.urls import path
from . import views

urlpatterns = [
    # Delivery management endpoints (primary workflow)
    path('deliveries/', views.get_inbound_deliveries, name='delivery-list'),
    path('deliveries/<str:pk>/', views.get_inbound_delivery, name='delivery-detail'),
    path('search/', views.search_deliveries, name='search-deliveries'),
    path('deliveries/receive', views.create_delivery_receipt, name='create-delivery-receipt'),

    # Receipt approval workflow endpoints
    path('receipts/<int:receipt_id>/approve/', views.approve_delivery_receipt, name='approve-receipt'),
    path('receipts/<int:receipt_id>/reject/', views.reject_delivery_receipt, name='reject-receipt'),
    path('receipts/<int:receipt_id>/update/', views.update_rejected_receipt, name='update-receipt'),
    path('approvals/pending/', views.get_pending_approvals, name='pending-approvals'),
]