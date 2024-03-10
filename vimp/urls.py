"""URL Configuration"""

from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from django.shortcuts import redirect

admin.site.site_header = "Food Concepts | VIMP"
admin.site.site_title = "Food Concepts | VIMP"
admin.site.index_title = "Food Concepts | VIMP"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('verifysetup', lambda request: redirect('api/v1/onboard' + request.get_full_path())),
    path('api/v1/', include('api_service.urls')),
    path('egrn/v1/', include('egrn_service.urls')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)