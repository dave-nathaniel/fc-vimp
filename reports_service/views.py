import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Q, F
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated

from overrides.authenticate import CombinedAuthentication
from overrides.rest_framework import APIResponse, CustomPagination

from egrn_service.models import GoodsReceivedNote, GoodsReceivedLineItem
from invoice_service.models import Invoice
from approval_service.models import Signature

from .models import WeeklyReport
from .serializers import WeeklyReportSerializer, WeeklyReportSummarySerializer


logger = logging.getLogger(__name__)
paginator = CustomPagination()


def get_week_boundaries(date=None, previous_week=False):
    """
    Get the Monday and Sunday of the week containing the given date.
    If previous_week is True, returns the previous completed week.
    """
    if date is None:
        date = timezone.now().date()
    elif isinstance(date, datetime):
        date = date.date()
    
    # Get the Monday of the week containing the date
    days_since_monday = date.weekday()
    monday = date - timedelta(days=days_since_monday)
    
    if previous_week:
        monday = monday - timedelta(days=7)
    
    sunday = monday + timedelta(days=6)
    
    return monday, sunday


def calculate_weekly_report_data(week_start, week_end):
    """
    Calculate all metrics for a weekly report.
    Returns a dictionary with all report data.
    """
    # Calculate ISO week number and year
    week_number = week_start.isocalendar()[1]
    year = week_start.isocalendar()[0]
    
    # === GRN Metrics ===
    grns_in_week = GoodsReceivedNote.objects.filter(
        created__gte=week_start,
        created__lte=week_end,
        is_nullified=False
    ).select_related('purchase_order__vendor')
    
    total_grns = grns_in_week.count()
    
    # Get GRN line items for the week
    grn_line_items = GoodsReceivedLineItem.objects.filter(
        grn__in=grns_in_week
    ).select_related(
        'purchase_order_line_item__delivery_store'
    )
    
    total_line_items = grn_line_items.count()
    
    # Aggregate GRN values
    grn_aggregates = grn_line_items.aggregate(
        total_net=Coalesce(Sum('net_value_received'), Decimal('0')),
        total_gross=Coalesce(Sum('gross_value_received'), Decimal('0')),
    )
    
    total_net_value = grn_aggregates['total_net']
    total_gross_value = grn_aggregates['total_gross']
    total_tax = total_gross_value - total_net_value
    
    # Unique vendors with goods received
    unique_vendors_received = grns_in_week.values(
        'purchase_order__vendor'
    ).distinct().count()
    
    # Unique stores that received goods
    unique_stores = grn_line_items.values(
        'purchase_order_line_item__delivery_store'
    ).distinct().count()
    
    # === Invoice Metrics ===
    # Invoices created during the week
    invoices_created_in_week = Invoice.objects.filter(
        date_created__date__gte=week_start,
        date_created__date__lte=week_end
    )
    total_invoices_created = invoices_created_in_week.count()
    
    # Get the content type for Invoice model
    invoice_content_type = ContentType.objects.get_for_model(Invoice)
    
    # Find invoices that were fully approved during the week
    # An invoice is approved when its last signature is accepting and it's completely signed
    approved_signatures = Signature.objects.filter(
        signable_type=invoice_content_type,
        accepted=True,
        date_signed__date__gte=week_start,
        date_signed__date__lte=week_end
    ).values_list('signable_id', flat=True)
    
    # Get invoices that were approved (have final accepting signature in this week)
    approved_invoice_ids = []
    for invoice_id in set(approved_signatures):
        try:
            invoice = Invoice.objects.get(id=invoice_id)
            if invoice.is_accepted and invoice.is_completely_signed:
                # Check if the last signature was made this week
                last_sig = invoice.get_last_signature()
                if (last_sig and 
                    last_sig.date_signed.date() >= week_start and 
                    last_sig.date_signed.date() <= week_end):
                    approved_invoice_ids.append(invoice_id)
        except Invoice.DoesNotExist:
            continue
    
    total_invoices_approved = len(approved_invoice_ids)
    
    # Calculate total approved payment value with optimized query
    approved_invoices = Invoice.objects.filter(id__in=approved_invoice_ids)
    total_approved_value = Decimal('0')
    
    for invoice in approved_invoices.prefetch_related('invoice_line_items'):
        gross_total = invoice.invoice_line_items.aggregate(
            total=Coalesce(Sum('gross_total'), Decimal('0'))
        )['total']
        total_approved_value += gross_total
    
    # Unique vendors with approved payments
    unique_vendors_paid = approved_invoices.values(
        'purchase_order__vendor'
    ).distinct().count()
    
    # Rejected invoices during the week
    rejected_signatures = Signature.objects.filter(
        signable_type=invoice_content_type,
        accepted=False,
        date_signed__date__gte=week_start,
        date_signed__date__lte=week_end
    ).values_list('signable_id', flat=True)
    
    rejected_invoice_ids = set()
    for invoice_id in set(rejected_signatures):
        try:
            invoice = Invoice.objects.get(id=invoice_id)
            if invoice.is_rejected:
                rejected_invoice_ids.add(invoice_id)
        except Invoice.DoesNotExist:
            continue
    
    total_invoices_rejected = len(rejected_invoice_ids)
    
    # Pending invoices (created but not fully signed or rejected at week end)
    total_invoices_pending = invoices_created_in_week.exclude(
        id__in=list(approved_invoice_ids) + list(rejected_invoice_ids)
    ).count()
    
    # Build metadata with breakdowns
    metadata = {
        'grn_breakdown': {
            'by_date': _get_daily_breakdown(grns_in_week, 'created', week_start, week_end),
        },
        'approval_breakdown': {
            'approved_invoice_ids': approved_invoice_ids,
            'rejected_invoice_ids': list(rejected_invoice_ids),
        }
    }
    
    return {
        'week_start_date': week_start,
        'week_end_date': week_end,
        'week_number': week_number,
        'year': year,
        'total_grns_received': total_grns,
        'total_grn_line_items': total_line_items,
        'total_net_value_received': total_net_value,
        'total_gross_value_received': total_gross_value,
        'total_tax_amount': total_tax,
        'total_invoices_created': total_invoices_created,
        'total_invoices_approved': total_invoices_approved,
        'total_approved_payment_value': total_approved_value,
        'total_invoices_rejected': total_invoices_rejected,
        'total_invoices_pending': total_invoices_pending,
        'unique_vendors_received': unique_vendors_received,
        'unique_vendors_paid': unique_vendors_paid,
        'unique_stores_received': unique_stores,
        'metadata': metadata,
    }


def _get_daily_breakdown(queryset, date_field, week_start, week_end):
    """
    Get a daily breakdown of counts for the given queryset.
    """
    breakdown = {}
    current_date = week_start
    
    while current_date <= week_end:
        filter_kwargs = {f'{date_field}': current_date}
        count = queryset.filter(**filter_kwargs).count()
        breakdown[current_date.isoformat()] = count
        current_date += timedelta(days=1)
    
    return breakdown


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
@permission_classes([IsAuthenticated])
def get_weekly_report(request):
    """
    Get the weekly report for a specific week or the most recent completed week.
    
    Query Parameters:
        - week_start: Start date of the week (YYYY-MM-DD format). If not provided,
                      returns the most recent completed week.
        - year: Year (optional, used with week_number)
        - week_number: ISO week number (optional, used with year)
        - regenerate: If 'true', forces regeneration of the report even if cached
    """
    try:
        week_start = None
        regenerate = request.query_params.get('regenerate', '').lower() == 'true'
        
        # Parse date parameters
        if request.query_params.get('week_start'):
            try:
                week_start = datetime.strptime(
                    request.query_params.get('week_start'),
                    '%Y-%m-%d'
                ).date()
            except ValueError:
                return APIResponse(
                    "Invalid date format. Use YYYY-MM-DD.",
                    status.HTTP_400_BAD_REQUEST
                )
        elif request.query_params.get('year') and request.query_params.get('week_number'):
            try:
                year = int(request.query_params.get('year'))
                week_num = int(request.query_params.get('week_number'))
                # Calculate the date from year and week number
                week_start = datetime.strptime(f'{year}-W{week_num:02d}-1', '%G-W%V-%u').date()
            except (ValueError, TypeError):
                return APIResponse(
                    "Invalid year or week_number.",
                    status.HTTP_400_BAD_REQUEST
                )
        
        # Get week boundaries
        if week_start:
            monday, sunday = get_week_boundaries(week_start)
        else:
            # Default to previous completed week
            monday, sunday = get_week_boundaries(previous_week=True)
        
        # Calculate ISO week info
        week_number = monday.isocalendar()[1]
        year = monday.isocalendar()[0]
        
        # Try to get existing report from database
        existing_report = None
        if not regenerate:
            try:
                existing_report = WeeklyReport.objects.get(
                    year=year,
                    week_number=week_number
                )
            except WeeklyReport.DoesNotExist:
                pass
        
        if existing_report and not regenerate:
            serializer = WeeklyReportSerializer(existing_report)
            return APIResponse(
                "Weekly report retrieved from cache.",
                status.HTTP_200_OK,
                data=serializer.data
            )
        
        # Generate new report data
        report_data = calculate_weekly_report_data(monday, sunday)
        
        # Save or update the report
        report, created = WeeklyReport.objects.update_or_create(
            year=year,
            week_number=week_number,
            defaults=report_data
        )
        
        serializer = WeeklyReportSerializer(report)
        message = "Weekly report generated." if created else "Weekly report regenerated."
        
        return APIResponse(message, status.HTTP_200_OK, data=serializer.data)
        
    except Exception as e:
        logger.error(f"Error generating weekly report: {e}")
        return APIResponse(
            f"Internal Error: {e}",
            status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
@permission_classes([IsAuthenticated])
def get_weekly_report_history(request):
    """
    Get historical weekly reports with pagination.
    
    Query Parameters:
        - year: Filter by year (optional)
        - page: Page number for pagination
        - size: Page size
    """
    try:
        reports = WeeklyReport.objects.all()
        
        # Filter by year if provided
        year = request.query_params.get('year')
        if year:
            try:
                reports = reports.filter(year=int(year))
            except ValueError:
                return APIResponse(
                    "Invalid year format.",
                    status.HTTP_400_BAD_REQUEST
                )
        
        if reports.exists():
            paginated = paginator.paginate_queryset(reports, request)
            serializer = WeeklyReportSummarySerializer(paginated, many=True)
            paginated_data = paginator.get_paginated_response(serializer.data).data
            return APIResponse(
                "Weekly report history retrieved.",
                status.HTTP_200_OK,
                data=paginated_data
            )
        
        return APIResponse(
            "No weekly reports found.",
            status.HTTP_404_NOT_FOUND
        )
        
    except Exception as e:
        logger.error(f"Error retrieving weekly report history: {e}")
        return APIResponse(
            f"Internal Error: {e}",
            status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
@permission_classes([IsAuthenticated])
def get_current_week_summary(request):
    """
    Get a real-time summary for the current week (in progress).
    This is not stored but calculated on-the-fly.
    """
    try:
        monday, sunday = get_week_boundaries()
        today = timezone.now().date()
        
        # Calculate report data for current week up to today
        report_data = calculate_weekly_report_data(monday, today)
        
        # Add context about the week being in progress
        report_data['is_complete'] = False
        report_data['days_remaining'] = (sunday - today).days
        report_data['report_as_of'] = today.isoformat()
        
        return APIResponse(
            "Current week summary generated.",
            status.HTTP_200_OK,
            data=report_data
        )
        
    except Exception as e:
        logger.error(f"Error generating current week summary: {e}")
        return APIResponse(
            f"Internal Error: {e}",
            status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([CombinedAuthentication])
@permission_classes([IsAuthenticated])
def get_weekly_comparison(request):
    """
    Compare the current week with the previous week.
    
    Returns metrics with percentage changes.
    """
    try:
        # Get current week data
        current_monday, current_sunday = get_week_boundaries()
        today = timezone.now().date()
        current_data = calculate_weekly_report_data(current_monday, today)
        
        # Get previous week data
        prev_monday, prev_sunday = get_week_boundaries(previous_week=True)
        
        # Try to get from cache first
        prev_week_number = prev_monday.isocalendar()[1]
        prev_year = prev_monday.isocalendar()[0]
        
        try:
            prev_report = WeeklyReport.objects.get(
                year=prev_year,
                week_number=prev_week_number
            )
            previous_data = WeeklyReportSerializer(prev_report).data
        except WeeklyReport.DoesNotExist:
            previous_data = calculate_weekly_report_data(prev_monday, prev_sunday)
        
        def calculate_change(current, previous):
            """Calculate percentage change between two values."""
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return round(((current - previous) / previous) * 100, 2)
        
        comparison = {
            'current_week': {
                'week_number': current_data['week_number'],
                'year': current_data['year'],
                'week_start_date': current_data['week_start_date'].isoformat() if hasattr(current_data['week_start_date'], 'isoformat') else current_data['week_start_date'],
                'week_end_date': current_data['week_end_date'].isoformat() if hasattr(current_data['week_end_date'], 'isoformat') else current_data['week_end_date'],
                'is_complete': False,
                'data': {
                    'total_grns_received': current_data['total_grns_received'],
                    'total_gross_value_received': float(current_data['total_gross_value_received']),
                    'total_invoices_approved': current_data['total_invoices_approved'],
                    'total_approved_payment_value': float(current_data['total_approved_payment_value']),
                }
            },
            'previous_week': {
                'week_number': previous_data.get('week_number'),
                'year': previous_data.get('year'),
                'week_start_date': previous_data.get('week_start_date'),
                'week_end_date': previous_data.get('week_end_date'),
                'is_complete': True,
                'data': {
                    'total_grns_received': previous_data.get('total_grns_received', 0),
                    'total_gross_value_received': float(previous_data.get('total_gross_value_received', 0)),
                    'total_invoices_approved': previous_data.get('total_invoices_approved', 0),
                    'total_approved_payment_value': float(previous_data.get('total_approved_payment_value', 0)),
                }
            },
            'changes': {
                'grns_received_change': calculate_change(
                    current_data['total_grns_received'],
                    previous_data.get('total_grns_received', 0)
                ),
                'gross_value_change': calculate_change(
                    float(current_data['total_gross_value_received']),
                    float(previous_data.get('total_gross_value_received', 0))
                ),
                'invoices_approved_change': calculate_change(
                    current_data['total_invoices_approved'],
                    previous_data.get('total_invoices_approved', 0)
                ),
                'approved_payment_change': calculate_change(
                    float(current_data['total_approved_payment_value']),
                    float(previous_data.get('total_approved_payment_value', 0))
                ),
            }
        }
        
        return APIResponse(
            "Weekly comparison generated.",
            status.HTTP_200_OK,
            data=comparison
        )
        
    except Exception as e:
        logger.error(f"Error generating weekly comparison: {e}")
        return APIResponse(
            f"Internal Error: {e}",
            status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@authentication_classes([CombinedAuthentication])
@permission_classes([IsAuthenticated])
def generate_weekly_report(request):
    """
    Manually trigger generation of a weekly report for a specific week.
    This endpoint allows admins to backfill historical reports.
    
    Request Body:
        - week_start: Start date of the week (YYYY-MM-DD format)
        OR
        - year: Year
        - week_number: ISO week number
    """
    try:
        week_start = None
        
        if request.data.get('week_start'):
            try:
                week_start = datetime.strptime(
                    request.data.get('week_start'),
                    '%Y-%m-%d'
                ).date()
            except ValueError:
                return APIResponse(
                    "Invalid date format. Use YYYY-MM-DD.",
                    status.HTTP_400_BAD_REQUEST
                )
        elif request.data.get('year') and request.data.get('week_number'):
            try:
                year = int(request.data.get('year'))
                week_num = int(request.data.get('week_number'))
                week_start = datetime.strptime(f'{year}-W{week_num:02d}-1', '%G-W%V-%u').date()
            except (ValueError, TypeError):
                return APIResponse(
                    "Invalid year or week_number.",
                    status.HTTP_400_BAD_REQUEST
                )
        else:
            return APIResponse(
                "Please provide either 'week_start' or both 'year' and 'week_number'.",
                status.HTTP_400_BAD_REQUEST
            )
        
        monday, sunday = get_week_boundaries(week_start)
        week_number = monday.isocalendar()[1]
        year = monday.isocalendar()[0]
        
        # Generate report data
        report_data = calculate_weekly_report_data(monday, sunday)
        
        # Save or update the report
        report, created = WeeklyReport.objects.update_or_create(
            year=year,
            week_number=week_number,
            defaults=report_data
        )
        
        serializer = WeeklyReportSerializer(report)
        message = "Weekly report created." if created else "Weekly report updated."
        
        return APIResponse(
            message,
            status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            data=serializer.data
        )
        
    except Exception as e:
        logger.error(f"Error manually generating weekly report: {e}")
        return APIResponse(
            f"Internal Error: {e}",
            status.HTTP_500_INTERNAL_SERVER_ERROR
        )
