from django.db import models
from django.utils import timezone
from datetime import timedelta


class WeeklyReport(models.Model):
    """
    Stores weekly report summaries for historical tracking and quick retrieval.
    Reports are generated for completed weeks (Monday to Sunday).
    """
    # Week identification
    week_start_date = models.DateField(
        verbose_name="Week Start Date",
        help_text="The Monday of the report week"
    )
    week_end_date = models.DateField(
        verbose_name="Week End Date",
        help_text="The Sunday of the report week"
    )
    week_number = models.PositiveIntegerField(
        verbose_name="Week Number",
        help_text="ISO week number of the year"
    )
    year = models.PositiveIntegerField(verbose_name="Year")
    
    # GRN Metrics
    total_grns_received = models.PositiveIntegerField(
        default=0,
        verbose_name="Total GRNs Received",
        help_text="Total number of Goods Received Notes created during the week"
    )
    total_grn_line_items = models.PositiveIntegerField(
        default=0,
        verbose_name="Total GRN Line Items",
        help_text="Total number of line items across all GRNs"
    )
    total_net_value_received = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        verbose_name="Total Net Value Received",
        help_text="Sum of net values from all GRN line items"
    )
    total_gross_value_received = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        verbose_name="Total Gross Value Received",
        help_text="Sum of gross values (including tax) from all GRN line items"
    )
    total_tax_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        verbose_name="Total Tax Amount",
        help_text="Total tax amount (gross - net)"
    )
    
    # Invoice/Payment Metrics
    total_invoices_created = models.PositiveIntegerField(
        default=0,
        verbose_name="Total Invoices Created",
        help_text="Total number of invoices created during the week"
    )
    total_invoices_approved = models.PositiveIntegerField(
        default=0,
        verbose_name="Total Invoices Approved",
        help_text="Total number of invoices fully approved during the week"
    )
    total_approved_payment_value = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        verbose_name="Total Approved Payment Value",
        help_text="Total gross value of approved invoices (vendor payments processed)"
    )
    total_invoices_rejected = models.PositiveIntegerField(
        default=0,
        verbose_name="Total Invoices Rejected",
        help_text="Total number of invoices rejected during the week"
    )
    total_invoices_pending = models.PositiveIntegerField(
        default=0,
        verbose_name="Total Invoices Pending",
        help_text="Total number of invoices still pending approval at week end"
    )
    
    # Vendor Metrics
    unique_vendors_received = models.PositiveIntegerField(
        default=0,
        verbose_name="Unique Vendors (Received)",
        help_text="Number of unique vendors with goods received"
    )
    unique_vendors_paid = models.PositiveIntegerField(
        default=0,
        verbose_name="Unique Vendors (Paid)",
        help_text="Number of unique vendors with approved payments"
    )
    
    # Store Metrics
    unique_stores_received = models.PositiveIntegerField(
        default=0,
        verbose_name="Unique Stores",
        help_text="Number of unique stores that received goods"
    )
    
    # Report metadata
    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional report data or breakdowns"
    )
    
    class Meta:
        verbose_name = "Weekly Report"
        verbose_name_plural = "Weekly Reports"
        ordering = ['-year', '-week_number']
        unique_together = ['year', 'week_number']
        indexes = [
            models.Index(fields=['year', 'week_number']),
            models.Index(fields=['week_start_date']),
        ]
    
    def __str__(self):
        return f"Week {self.week_number}, {self.year} ({self.week_start_date} to {self.week_end_date})"
    
    @classmethod
    def get_week_boundaries(cls, date=None):
        """
        Get the Monday and Sunday of the week containing the given date.
        If no date is provided, returns the previous completed week.
        """
        if date is None:
            date = timezone.now().date()
        
        # Get the Monday of the current week
        days_since_monday = date.weekday()
        monday = date - timedelta(days=days_since_monday)
        sunday = monday + timedelta(days=6)
        
        return monday, sunday
    
    @classmethod
    def get_previous_week_boundaries(cls, date=None):
        """
        Get the Monday and Sunday of the previous completed week.
        """
        if date is None:
            date = timezone.now().date()
        
        # Get Monday of current week, then go back 7 days
        days_since_monday = date.weekday()
        current_monday = date - timedelta(days=days_since_monday)
        previous_monday = current_monday - timedelta(days=7)
        previous_sunday = previous_monday + timedelta(days=6)
        
        return previous_monday, previous_sunday
