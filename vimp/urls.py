"""URL Configuration"""

from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from django.shortcuts import redirect
from egrn_service.admin import inventory_tools
from core_service import performance_views

admin.site.site_header = "Food Concepts"
admin.site.site_title = "eGRN & VIMP"
admin.site.index_title = "Admin Console"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('inventory-tools/', include(inventory_tools.urls)),
    path('verifysetup', lambda request: redirect('api/v1/onboard' + request.get_full_path())),
    path('api/v1/', include('api_service.urls')),
    path('egrn/v1/', include('egrn_service.urls')),
    path('approvals/v1/', include('approval_service.urls')),
    
    # Performance monitoring endpoints
    path('admin/performance/', performance_views.performance_dashboard, name='performance_dashboard'),
    path('admin/performance/cache/', performance_views.cache_statistics, name='cache_statistics'),
    path('admin/performance/database/', performance_views.database_statistics, name='database_statistics'),
    path('health/', performance_views.health_check, name='health_check'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)