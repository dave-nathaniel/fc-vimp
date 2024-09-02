from django.urls import path
from approval_service.views import sign_signable_view, get_user_signable_view, get_signable_view, track_signable_view


urlpatterns = [
	# Sign
    path('sign/<str:target_class>/<int:object_id>', sign_signable_view),
	# Get signables for a specific user's role.
    path('get/<str:target_class>/<str:status_filter>', get_user_signable_view),
	# Get signables for a specific user's role.
    path('any/<str:target_class>/<str:status_filter>', get_signable_view),
	# Track all signatures for a specific signable object.
	path('track/<str:target_class>/<int:object_id>', track_signable_view),
]