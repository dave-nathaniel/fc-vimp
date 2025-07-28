from django.urls import path
from . import views

# URL patterns for stock movement service
urlpatterns = [
    # Sales Orders
    path('sales-orders', views.get_sales_orders, name='get_sales_orders'),
    path('sales-orders/<int:sales_order_id>', views.get_sales_order, name='get_sales_order'),
    
    # Goods Issue
    path('goods-issue', views.create_goods_issue, name='create_goods_issue'),
    path('goods-issues', views.get_goods_issues, name='get_goods_issues'),
    path('goods-issues/<int:issue_number>', views.get_goods_issue, name='get_goods_issue'),
    
    # Transfer Receipt
    path('transfer-receipt', views.create_transfer_receipt, name='create_transfer_receipt'),
    path('transfer-receipts', views.get_transfer_receipts, name='get_transfer_receipts'),
    path('transfer-receipts/<int:receipt_number>', views.get_transfer_receipt, name='get_transfer_receipt'),
    
    # Pending Operations
    path('pending-issues', views.get_pending_issues, name='get_pending_issues'),
    path('pending-receipts', views.get_pending_receipts, name='get_pending_receipts'),
    
    # Summary and Reports
    path('transfer-summary', views.get_transfer_summary, name='get_transfer_summary'),
    
    # User Authorization
    path('user-store-authorizations', views.get_user_store_authorizations, name='get_user_store_authorizations'),
]