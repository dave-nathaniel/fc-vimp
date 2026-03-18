from django.db import models
from django.core.exceptions import ValidationError
import requests
from requests.auth import HTTPBasicAuth
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)


class ImprestItem(models.Model):
    """
    Model to store G/L Accounts from SAP ByD for imprest and expense tracking.
    Synced from FINGLACCT data source via Analytics OData API.
    """

    ACCOUNT_TYPE_CHOICES = [
        ('COSEXP', 'Cost/Expense Account'),
        ('CASH', 'Cash/Bank Account'),
        ('OTHER', 'Other Account Type'),
    ]

    # Primary fields from SAP ByD
    gl_account = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        verbose_name="G/L Account Number",
        help_text="Chart of accounts G/L account number (C_Glacct)"
    )

    description = models.CharField(
        max_length=255,
        verbose_name="Description",
        help_text="G/L Account description (T_Description)"
    )

    account_type = models.CharField(
        max_length=20,
        choices=ACCOUNT_TYPE_CHOICES,
        db_index=True,
        verbose_name="Account Type",
        help_text="G/L Account type code (C_GlacctTc)"
    )

    chart_of_accounts = models.CharField(
        max_length=10,
        default='FCOA',
        verbose_name="Chart of Accounts",
        help_text="Chart of accounts identifier (C_Chofacct)"
    )

    # Metadata fields
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Active Status",
        help_text="Whether this account is active for use"
    )

    last_synced = models.DateTimeField(
        auto_now=True,
        verbose_name="Last Synced",
        help_text="Timestamp of last sync from SAP ByD"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At"
    )

    class Meta:
        db_table = 'imprest_items'
        verbose_name = 'Imprest Item'
        verbose_name_plural = 'Imprest Items'
        ordering = ['gl_account']
        indexes = [
            models.Index(fields=['gl_account']),
            models.Index(fields=['account_type']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.gl_account} - {self.description}"

    def clean(self):
        """Validate model fields"""
        super().clean()

        # Ensure GL account is not empty
        if not self.gl_account or not self.gl_account.strip():
            raise ValidationError({'gl_account': 'G/L Account number cannot be empty'})

        # Ensure description is not empty
        if not self.description or not self.description.strip():
            raise ValidationError({'description': 'Description cannot be empty'})

    @classmethod
    def sync_from_byd(cls, account_type=None, force_refresh=False):
        """
        Sync G/L Accounts from SAP ByD FINGLACCT data source.

        Args:
            account_type (str, optional): Filter by account type (COSEXP, CASH, etc.)
            force_refresh (bool): If True, delete existing records and re-sync

        Returns:
            dict: Status information with count of created/updated records
        """
        sap_url = os.getenv('SAP_URL')
        sap_comm_user = os.getenv('SAP_COMM_USER')
        sap_comm_pass = os.getenv('SAP_COMM_PASS')

        if not all([sap_url, sap_comm_user, sap_comm_pass]):
            raise ValueError("SAP credentials not configured in environment")

        # Build OData URL
        analytics_base = f"{sap_url}/sap/byd/odata/analytics/ds"
        url = f"{analytics_base}/Finglacct.svc/Finglacct?$format=json&$select=C_Glacct,T_Description,C_GlacctTc,C_Chofacct"

        if account_type:
            url += f"&$filter=C_GlacctTc eq '{account_type}'"

        # Make request to SAP ByD
        auth = HTTPBasicAuth(sap_comm_user, sap_comm_pass)
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.get(url, auth=auth, headers=headers, timeout=60)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to fetch data from SAP ByD: {str(e)}")

        # Parse response
        try:
            data = response.json()
            results = data.get('d', {}).get('results', [])
        except ValueError as e:
            raise Exception(f"Failed to parse SAP ByD response: {str(e)}")

        if not results:
            return {
                'status': 'success',
                'message': 'No records found in SAP ByD',
                'created': 0,
                'updated': 0,
                'total': 0
            }

        # Force refresh: delete existing records
        if force_refresh:
            delete_filter = {}
            if account_type:
                delete_filter['account_type'] = account_type
            deleted_count = cls.objects.filter(**delete_filter).delete()[0]
        else:
            deleted_count = 0

        # Create or update records
        created_count = 0
        updated_count = 0

        for item in results:
            gl_account = item.get('C_Glacct')
            description = item.get('T_Description', 'N/A')
            acct_type = item.get('C_GlacctTc', 'OTHER')
            chart_of_accounts = item.get('C_Chofacct', 'FCOA')

            if not gl_account:
                continue  # Skip invalid records

            # Create or update
            obj, created = cls.objects.update_or_create(
                gl_account=gl_account,
                defaults={
                    'description': description,
                    'account_type': acct_type,
                    'chart_of_accounts': chart_of_accounts,
                    'is_active': True,
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        return {
            'status': 'success',
            'message': f'Successfully synced {len(results)} records from SAP ByD',
            'created': created_count,
            'updated': updated_count,
            'deleted': deleted_count if force_refresh else 0,
            'total': len(results)
        }

    @classmethod
    def get_expense_accounts(cls):
        """Get all active expense accounts (COSEXP)"""
        return cls.objects.filter(account_type='COSEXP', is_active=True)

    @classmethod
    def get_bank_accounts(cls):
        """Get all active bank/cash accounts (CASH)"""
        return cls.objects.filter(account_type='CASH', is_active=True)
