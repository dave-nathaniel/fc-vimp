from django.urls import path
from . import views

urlpatterns = [
    path('sales-orders/', views.SalesOrderListView.as_view(), name='salesorder-list'),
    path('sales-orders/<int:pk>/', views.SalesOrderDetailView.as_view(), name='salesorder-detail'),
    path('goods-issues/', views.GoodsIssueNoteListView.as_view(), name='goodsissuenote-list'),
    path('goods-issues/<int:pk>/', views.GoodsIssueNoteDetailView.as_view(), name='goodsissuenote-detail'),
    path('transfer-receipts/', views.TransferReceiptNoteListView.as_view(), name='transferreceiptnote-list'),
    path('transfer-receipts/<int:pk>/', views.TransferReceiptNoteDetailView.as_view(), name='transferreceiptnote-detail'),
]