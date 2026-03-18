from rest_framework import serializers
from .models import ImprestItem


class ImprestItemSerializer(serializers.ModelSerializer):
    """
    Serializer for ImprestItem model with all fields.
    """

    account_type_display = serializers.CharField(
        source='get_account_type_display',
        read_only=True,
        help_text="Human-readable account type"
    )

    class Meta:
        model = ImprestItem
        fields = [
            'id',
            'gl_account',
            'description',
            'account_type',
            'account_type_display',
            'chart_of_accounts',
            'is_active',
            'last_synced',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'last_synced',
            'created_at',
            'updated_at',
        ]


class ImprestItemBriefSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for ImprestItem with essential fields only.
    Used for list endpoints to improve performance.
    """

    class Meta:
        model = ImprestItem
        fields = [
            'id',
            'gl_account',
            'description',
            'account_type',
        ]
