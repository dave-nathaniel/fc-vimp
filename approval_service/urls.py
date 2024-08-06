from django.urls import path
from approval_service.views import sign_signable_view, get_signable_view


urlpatterns = [
	# Sign
    path('sign/<str:target_class>/<int:object_id>', sign_signable_view),
	# Get pending for current user role
    path('get/<str:target_class>', get_signable_view),
]