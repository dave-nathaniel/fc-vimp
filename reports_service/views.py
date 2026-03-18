import logging
import json
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, renderer_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer, StaticHTMLRenderer

from overrides.authenticate import CombinedAuthentication
from overrides.rest_framework import APIResponse, CustomPagination

from egrn_service.models import GoodsReceivedNote, GoodsReceivedLineItem
from invoice_service.models import Invoice
from approval_service.models import Signature

from .models import WeeklyReport
from .serializers import WeeklyReportSerializer, WeeklyReportSummarySerializer


logger = logging.getLogger(__name__)
paginator = CustomPagination()


def _parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "t", "yes", "y", "on")
    return default


def _safe_json_body(request):
    """
    DRF does not reliably parse JSON bodies on GET requests.
    This helper tries to parse request.body as JSON and returns a dict.
    """
    try:
        raw = getattr(request, "body", b"") or b""
        if not raw:
            return {}
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        payload = json.loads(raw.decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _validate_email_recipients(emails):
    if not isinstance(emails, list):
        raise ValueError("'emails' must be a list of email strings.")

    cleaned = []
    seen = set()
    for item in emails:
        if not isinstance(item, str):
            continue
        email = item.strip()
        if not email:
            continue
        if email.lower() in seen:
            continue
        try:
            validate_email(email)
        except ValidationError:
            continue
        cleaned.append(email)
        seen.add(email.lower())

    if not cleaned:
        raise ValueError("No valid email recipients were provided in 'emails'.")

    return cleaned


def _fmt_int(value):
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def _fmt_money(value):
    try:
        if value is None:
            return "0.00"
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return f"{value:,.2f}"
    except Exception:
        return str(value)


def _weekly_report_email_context(report_like, *, title="Weekly Operational Summary", subtitle=None, is_complete=True, report_as_of=None):
    """
    Builds a template-safe context. Accepts a WeeklyReport model or a dict-like report.
    """
    def get_attr(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    week_start = get_attr(report_like, "week_start_date")
    week_end = get_attr(report_like, "week_end_date")
    week_number = get_attr(report_like, "week_number")
    year = get_attr(report_like, "year")

    generated_at = get_attr(report_like, "generated_at")
    updated_at = get_attr(report_like, "updated_at")

    ctx = {
        "title": title,
        "subtitle": subtitle,
        "is_complete": is_complete,
        "report_as_of": report_as_of,
        "week_number": week_number,
        "year": year,
        "week_start_date": week_start,
        "week_end_date": week_end,
        "generated_at": generated_at,
        "updated_at": updated_at,
        # Metrics (formatted)
        "total_grns_received": _fmt_int(get_attr(report_like, "total_grns_received", 0)),
        "total_grn_line_items": _fmt_int(get_attr(report_like, "total_grn_line_items", 0)),
        "total_net_value_received": _fmt_money(get_attr(report_like, "total_net_value_received", 0)),
        "total_gross_value_received": _fmt_money(get_attr(report_like, "total_gross_value_received", 0)),
        "total_tax_amount": _fmt_money(get_attr(report_like, "total_tax_amount", 0)),
        "total_invoices_created": _fmt_int(get_attr(report_like, "total_invoices_created", 0)),
        "total_invoices_approved": _fmt_int(get_attr(report_like, "total_invoices_approved", 0)),
        "total_approved_payment_value": _fmt_money(get_attr(report_like, "total_approved_payment_value", 0)),
        "total_invoices_rejected": _fmt_int(get_attr(report_like, "total_invoices_rejected", 0)),
        "total_invoices_pending": _fmt_int(get_attr(report_like, "total_invoices_pending", 0)),
        "unique_vendors_received": _fmt_int(get_attr(report_like, "unique_vendors_received", 0)),
        "unique_vendors_paid": _fmt_int(get_attr(report_like, "unique_vendors_paid", 0)),
        "unique_stores_received": _fmt_int(get_attr(report_like, "unique_stores_received", 0)),
        "app_name": "VIMP",
    }

    return ctx


def _render_weekly_report_html(context):
    return render_to_string("reports_service/emails/weekly_report.html", context)


def _render_weekly_comparison_html(context):
    return render_to_string("reports_service/emails/weekly_comparison.html", context)


def _send_report_email(*, subject, html_body, recipients, text_body=None):
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None) or "no-reply@localhost"
    text_body = text_body or "Please view this message in an HTML-capable email client to see the report."
    msg = EmailMultiAlternatives(subject=subject, body=text_body, from_email=from_email, to=recipients)
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


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
@renderer_classes([JSONRenderer, StaticHTMLRenderer])
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
        body = _safe_json_body(request)
        send_email = _parse_bool(body.get("send_email"), False) or _parse_bool(request.query_params.get("send_email"), False)
        emails = body.get("emails", None)
        recipients = None
        if send_email:
            try:
                recipients = _validate_email_recipients(emails)
            except ValueError as ve:
                return APIResponse(str(ve), status.HTTP_400_BAD_REQUEST)

        render_html = request.query_params.get("format", "").lower() == "html" or request.query_params.get("html", "").lower() == "true"

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
        
        report = None
        created = False
        if existing_report and not regenerate:
            report = existing_report
        else:
            # Generate new report data
            report_data = calculate_weekly_report_data(monday, sunday)

            # Save or update the report
            report, created = WeeklyReport.objects.update_or_create(
                year=year,
                week_number=week_number,
                defaults=report_data
            )
        
        # Render HTML (for endpoint or email)
        subtitle = "Completed week summary" if True else None
        context = _weekly_report_email_context(report, subtitle=subtitle, is_complete=True)
        html_body = _render_weekly_report_html(context)

        emailed_to = []
        if send_email and recipients:
            subject = f"VIMP Weekly Report – Week {context.get('week_number')}, {context.get('year')}"
            text_body = (
                f"VIMP Weekly Report\n"
                f"Week {context.get('week_number')}, {context.get('year')}\n"
                f"Period: {context.get('week_start_date')} to {context.get('week_end_date')}\n"
            )
            _send_report_email(subject=subject, html_body=html_body, recipients=recipients, text_body=text_body)
            emailed_to = recipients

        if render_html:
            return HttpResponse(html_body, content_type="text/html")

        serializer = WeeklyReportSerializer(report)
        message = "Weekly report retrieved from cache." if (existing_report and not regenerate) else ("Weekly report generated." if created else "Weekly report regenerated.")
        data = serializer.data
        if send_email:
            data = {**data, "email_sent": True, "emailed_to": emailed_to}
        return APIResponse(message, status.HTTP_200_OK, data=data)
        
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
@renderer_classes([JSONRenderer, StaticHTMLRenderer])
@authentication_classes([CombinedAuthentication])
@permission_classes([IsAuthenticated])
def get_current_week_summary(request):
    """
    Get a real-time summary for the current week (in progress).
    This is not stored but calculated on-the-fly.
    """
    try:
        body = _safe_json_body(request)
        send_email = _parse_bool(body.get("send_email"), False) or _parse_bool(request.query_params.get("send_email"), False)
        emails = body.get("emails", None)
        recipients = None
        if send_email:
            try:
                recipients = _validate_email_recipients(emails)
            except ValueError as ve:
                return APIResponse(str(ve), status.HTTP_400_BAD_REQUEST)

        render_html = request.query_params.get("format", "").lower() == "html" or request.query_params.get("html", "").lower() == "true"

        monday, sunday = get_week_boundaries()
        today = timezone.now().date()
        
        # Calculate report data for current week up to today
        report_data = calculate_weekly_report_data(monday, today)
        
        # Add context about the week being in progress
        report_data['is_complete'] = False
        report_data['days_remaining'] = (sunday - today).days
        report_data['report_as_of'] = today.isoformat()
        
        # Render the same weekly template, but mark as in-progress
        report_data_for_template = {
            **report_data,
            "generated_at": timezone.now(),
            "updated_at": timezone.now(),
        }
        context = _weekly_report_email_context(
            report_data_for_template,
            title="Weekly Operational Summary (In Progress)",
            subtitle=f"As of {today.isoformat()}",
            is_complete=False,
            report_as_of=today.isoformat(),
        )
        html_body = _render_weekly_report_html(context)

        emailed_to = []
        if send_email and recipients:
            subject = f"VIMP Weekly Summary (In Progress) – Week {context.get('week_number')}, {context.get('year')}"
            text_body = (
                f"VIMP Weekly Summary (In Progress)\n"
                f"Week {context.get('week_number')}, {context.get('year')}\n"
                f"As of: {today.isoformat()}\n"
            )
            _send_report_email(subject=subject, html_body=html_body, recipients=recipients, text_body=text_body)
            emailed_to = recipients

        if render_html:
            return HttpResponse(html_body, content_type="text/html")

        response_data = report_data
        if send_email:
            response_data = {**response_data, "email_sent": True, "emailed_to": emailed_to}

        return APIResponse("Current week summary generated.", status.HTTP_200_OK, data=response_data)
        
    except Exception as e:
        logger.error(f"Error generating current week summary: {e}")
        return APIResponse(
            f"Internal Error: {e}",
            status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@renderer_classes([JSONRenderer, StaticHTMLRenderer])
@authentication_classes([CombinedAuthentication])
@permission_classes([IsAuthenticated])
def get_weekly_comparison(request):
    """
    Compare the current week with the previous week.
    
    Returns metrics with percentage changes.
    """
    try:
        body = _safe_json_body(request)
        send_email = _parse_bool(body.get("send_email"), False) or _parse_bool(request.query_params.get("send_email"), False)
        emails = body.get("emails", None)
        recipients = None
        if send_email:
            try:
                recipients = _validate_email_recipients(emails)
            except ValueError as ve:
                return APIResponse(str(ve), status.HTTP_400_BAD_REQUEST)

        render_html = request.query_params.get("format", "").lower() == "html" or request.query_params.get("html", "").lower() == "true"

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

        # Render and/or email comparison
        context = {
            "title": "Weekly Comparison (Current vs Previous)",
            "subtitle": f"As of {today.isoformat()}",
            "current_week": comparison["current_week"],
            "previous_week": comparison["previous_week"],
            "changes": comparison["changes"],
            "app_name": "VIMP",
        }
        html_body = _render_weekly_comparison_html(context)

        emailed_to = []
        if send_email and recipients:
            subject = f"VIMP Weekly Comparison – Week {comparison['current_week']['week_number']}, {comparison['current_week']['year']}"
            text_body = (
                f"VIMP Weekly Comparison\n"
                f"Current week: {comparison['current_week']['week_start_date']} to {comparison['current_week']['week_end_date']} (in progress)\n"
                f"Previous week: {comparison['previous_week']['week_start_date']} to {comparison['previous_week']['week_end_date']}\n"
            )
            _send_report_email(subject=subject, html_body=html_body, recipients=recipients, text_body=text_body)
            emailed_to = recipients

        if render_html:
            return HttpResponse(html_body, content_type="text/html")

        response_data = comparison
        if send_email:
            response_data = {**response_data, "email_sent": True, "emailed_to": emailed_to}

        return APIResponse("Weekly comparison generated.", status.HTTP_200_OK, data=response_data)
        
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
