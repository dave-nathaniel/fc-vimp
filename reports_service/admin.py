from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import WeeklyReport


@admin.register(WeeklyReport)
class WeeklyReportAdmin(ModelAdmin):
    list_display = [
        'week_number',
        'year',
        'week_start_date',
        'week_end_date',
        'total_grns_received',
        'total_gross_value_received',
        'total_invoices_approved',
        'total_approved_payment_value',
        'generated_at',
    ]
    list_filter = ['year', 'week_number']
    search_fields = ['year', 'week_number']
    readonly_fields = [
        'week_start_date',
        'week_end_date',
        'week_number',
        'year',
        'total_grns_received',
        'total_grn_line_items',
        'total_net_value_received',
        'total_gross_value_received',
        'total_tax_amount',
        'total_invoices_created',
        'total_invoices_approved',
        'total_approved_payment_value',
        'total_invoices_rejected',
        'total_invoices_pending',
        'unique_vendors_received',
        'unique_vendors_paid',
        'unique_stores_received',
        'generated_at',
        'updated_at',
    ]
    ordering = ['-year', '-week_number']
    
    fieldsets = (
        ('Week Information', {
            'fields': ('week_number', 'year', 'week_start_date', 'week_end_date')
        }),
        ('Goods Received Metrics', {
            'fields': (
                'total_grns_received',
                'total_grn_line_items',
                'total_net_value_received',
                'total_gross_value_received',
                'total_tax_amount',
            )
        }),
        ('Invoice & Payment Metrics', {
            'fields': (
                'total_invoices_created',
                'total_invoices_approved',
                'total_approved_payment_value',
                'total_invoices_rejected',
                'total_invoices_pending',
            )
        }),
        ('Vendor & Store Metrics', {
            'fields': (
                'unique_vendors_received',
                'unique_vendors_paid',
                'unique_stores_received',
            )
        }),
        ('Metadata', {
            'fields': ('metadata', 'generated_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
