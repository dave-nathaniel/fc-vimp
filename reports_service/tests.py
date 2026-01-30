from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import WeeklyReport
from .views import get_week_boundaries, calculate_weekly_report_data


class WeeklyReportModelTest(TestCase):
    """Tests for the WeeklyReport model."""
    
    def test_create_weekly_report(self):
        """Test creating a weekly report."""
        monday, sunday = get_week_boundaries(previous_week=True)
        
        report = WeeklyReport.objects.create(
            week_start_date=monday,
            week_end_date=sunday,
            week_number=monday.isocalendar()[1],
            year=monday.isocalendar()[0],
            total_grns_received=10,
            total_gross_value_received=Decimal('100000.00'),
            total_invoices_approved=5,
            total_approved_payment_value=Decimal('50000.00'),
        )
        
        self.assertEqual(report.total_grns_received, 10)
        self.assertEqual(report.total_gross_value_received, Decimal('100000.00'))
    
    def test_week_boundaries_unique_constraint(self):
        """Test that only one report can exist per week."""
        monday, sunday = get_week_boundaries(previous_week=True)
        week_number = monday.isocalendar()[1]
        year = monday.isocalendar()[0]
        
        WeeklyReport.objects.create(
            week_start_date=monday,
            week_end_date=sunday,
            week_number=week_number,
            year=year,
        )
        
        # Attempting to create another report for the same week should fail
        with self.assertRaises(Exception):
            WeeklyReport.objects.create(
                week_start_date=monday,
                week_end_date=sunday,
                week_number=week_number,
                year=year,
            )


class WeekBoundariesTest(TestCase):
    """Tests for week boundary calculations."""
    
    def test_get_week_boundaries_returns_monday_sunday(self):
        """Test that get_week_boundaries returns correct Monday and Sunday."""
        # Use a known date (Wednesday, Jan 15, 2025)
        from datetime import date
        test_date = date(2025, 1, 15)
        
        monday, sunday = get_week_boundaries(test_date)
        
        # Monday should be Jan 13, 2025
        self.assertEqual(monday.weekday(), 0)  # 0 = Monday
        self.assertEqual(sunday.weekday(), 6)  # 6 = Sunday
        self.assertEqual((sunday - monday).days, 6)
    
    def test_previous_week_boundaries(self):
        """Test getting previous week boundaries."""
        monday, sunday = get_week_boundaries(previous_week=True)
        today = timezone.now().date()
        
        # Previous week should be at least 7 days before today
        self.assertLess(sunday, today)
        self.assertEqual(monday.weekday(), 0)
        self.assertEqual(sunday.weekday(), 6)
