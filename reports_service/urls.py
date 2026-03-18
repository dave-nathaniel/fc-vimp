from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # Get weekly report (specific week or most recent completed week)
    path('weekly/', views.get_weekly_report, name='weekly_report'),
    path('weekly/html/', views.get_weekly_report, name='weekly_report_html'),
    
    # Get historical weekly reports with pagination
    path('weekly/history/', views.get_weekly_report_history, name='weekly_report_history'),
    
    # Get current week summary (in progress, real-time)
    path('weekly/current/', views.get_current_week_summary, name='current_week_summary'),
    path('weekly/current/html/', views.get_current_week_summary, name='current_week_summary_html'),
    
    # Compare current week with previous week
    path('weekly/compare/', views.get_weekly_comparison, name='weekly_comparison'),
    path('weekly/compare/html/', views.get_weekly_comparison, name='weekly_comparison_html'),
    
    # Manually generate/regenerate a weekly report
    path('weekly/generate/', views.generate_weekly_report, name='generate_weekly_report'),
]
