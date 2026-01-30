from rest_framework import serializers
from .models import WeeklyReport


class WeeklyReportSerializer(serializers.ModelSerializer):
    """
    Full serializer for WeeklyReport with all fields.
    """
    
    class Meta:
        model = WeeklyReport
        fields = [
            'id',
            'week_start_date',
            'week_end_date',
            'week_number',
            'year',
            # GRN Metrics
            'total_grns_received',
            'total_grn_line_items',
            'total_net_value_received',
            'total_gross_value_received',
            'total_tax_amount',
            # Invoice/Payment Metrics
            'total_invoices_created',
            'total_invoices_approved',
            'total_approved_payment_value',
            'total_invoices_rejected',
            'total_invoices_pending',
            # Vendor & Store Metrics
            'unique_vendors_received',
            'unique_vendors_paid',
            'unique_stores_received',
            # Metadata
            'generated_at',
            'updated_at',
            'metadata',
        ]
        read_only_fields = fields


class WeeklyReportSummarySerializer(serializers.ModelSerializer):
    """
    Summary serializer for WeeklyReport listing (without detailed metadata).
    """
    
    class Meta:
        model = WeeklyReport
        fields = [
            'id',
            'week_start_date',
            'week_end_date',
            'week_number',
            'year',
            'total_grns_received',
            'total_gross_value_received',
            'total_invoices_approved',
            'total_approved_payment_value',
            'generated_at',
        ]
        read_only_fields = fields


class WeeklyReportCreateSerializer(serializers.Serializer):
    """
    Serializer for creating/triggering weekly report generation.
    """
    week_start = serializers.DateField(required=False)
    year = serializers.IntegerField(required=False, min_value=2000, max_value=2100)
    week_number = serializers.IntegerField(required=False, min_value=1, max_value=53)
    
    def validate(self, data):
        if not data.get('week_start') and not (data.get('year') and data.get('week_number')):
            raise serializers.ValidationError(
                "Please provide either 'week_start' or both 'year' and 'week_number'."
            )
        return data
