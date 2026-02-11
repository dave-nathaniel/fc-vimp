from django.contrib import admin
from django.utils.html import format_html
from .models import ImprestItem


@admin.register(ImprestItem)
class ImprestItemAdmin(admin.ModelAdmin):
    """Admin interface for Imprest Items (G/L Accounts)"""

    list_display = [
        'gl_account',
        'description',
        'account_type_badge',
        'chart_of_accounts',
        'is_active_badge',
        'last_synced',
    ]

    list_filter = [
        'account_type',
        'is_active',
        'chart_of_accounts',
        'last_synced',
    ]

    search_fields = [
        'gl_account',
        'description',
    ]

    readonly_fields = [
        'last_synced',
        'created_at',
        'updated_at',
    ]

    fieldsets = (
        ('G/L Account Information', {
            'fields': (
                'gl_account',
                'description',
                'account_type',
                'chart_of_accounts',
            )
        }),
        ('Status', {
            'fields': (
                'is_active',
            )
        }),
        ('Metadata', {
            'fields': (
                'last_synced',
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',)
        }),
    )

    ordering = ['gl_account']

    list_per_page = 50

    def account_type_badge(self, obj):
        """Display account type with colored badge"""
        colors = {
            'COSEXP': '#f39c12',  # Orange for expenses
            'CASH': '#27ae60',    # Green for cash/bank
            'OTHER': '#95a5a6',   # Gray for others
        }
        color = colors.get(obj.account_type, '#95a5a6')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_account_type_display()
        )
    account_type_badge.short_description = 'Account Type'

    def is_active_badge(self, obj):
        """Display active status with badge"""
        if obj.is_active:
            return format_html(
                '<span style="background-color: #27ae60; color: white; padding: 3px 10px; '
                'border-radius: 3px; font-size: 11px;">✓ Active</span>'
            )
        else:
            return format_html(
                '<span style="background-color: #e74c3c; color: white; padding: 3px 10px; '
                'border-radius: 3px; font-size: 11px;">✗ Inactive</span>'
            )
    is_active_badge.short_description = 'Status'

    actions = ['activate_accounts', 'deactivate_accounts', 'sync_from_sap']

    def activate_accounts(self, request, queryset):
        """Activate selected accounts"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} account(s) activated successfully.')
    activate_accounts.short_description = 'Activate selected accounts'

    def deactivate_accounts(self, request, queryset):
        """Deactivate selected accounts"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} account(s) deactivated successfully.')
    deactivate_accounts.short_description = 'Deactivate selected accounts'

    def sync_from_sap(self, request, queryset):
        """Manually trigger sync from SAP ByD"""
        try:
            result = ImprestItem.sync_from_byd(force_refresh=False)
            self.message_user(
                request,
                f"Sync completed: {result['created']} created, "
                f"{result['updated']} updated, {result['total']} total"
            )
        except Exception as e:
            self.message_user(request, f'Sync failed: {str(e)}', level='error')
    sync_from_sap.short_description = 'Sync from SAP ByD'
