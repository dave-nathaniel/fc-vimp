from django.urls import path
from . import views

app_name = 'imprest_service'

urlpatterns = [
    # List and sync endpoints
    path('items/', views.get_imprest_items, name='imprest-items-list'),
    path('items/<str:gl_account>/', views.get_imprest_item, name='imprest-item-detail'),
    path('sync/', views.sync_imprest_items, name='imprest-sync'),

    # Convenience endpoints for specific account types
    path('expense-accounts/', views.get_expense_accounts, name='expense-accounts'),
    path('bank-accounts/', views.get_bank_accounts, name='bank-accounts'),
]
