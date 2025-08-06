from django.urls import path
from . import views

urlpatterns = [
    # Delivery management endpoints (primary workflow)
    path('deliveries/', views.get_inbound_deliveries, name='delivery-list'),
    path('deliveries/<str:pk>/', views.get_inbound_delivery, name='delivery-detail'),
    path('deliveries/search/', views.search_deliveries, name='search-deliveries'),
    path('deliveries/receive', views.create_delivery_receipt, name='create-delivery-receipt'),
    
    # Legacy endpoints (maintained for backwards compatibility)
    path('sales-orders/', views.SalesOrderListView.as_view(), name='salesorder-list'),
    path('sales-orders/<int:pk>/', views.SalesOrderDetailView.as_view(), name='salesorder-detail'),
    path('goods-issues/', views.GoodsIssueNoteListView.as_view(), name='goodsissuenote-list'),
    path('goods-issues/<int:pk>/', views.GoodsIssueNoteDetailView.as_view(), name='goodsissuenote-detail'),
    path('goods-issues/create/', views.create_goods_issue, name='create-goods-issue'),
    path('transfer-receipts/', views.TransferReceiptNoteListView.as_view(), name='transferreceiptnote-list'),
    path('transfer-receipts/<int:pk>/', views.TransferReceiptNoteDetailView.as_view(), name='transferreceiptnote-detail'),
    path('transfer-receipts/create/', views.create_transfer_receipt, name='create-transfer-receipt'),
]