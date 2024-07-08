from django.urls import path
from approval_service.views import sign_signable_view


urlpatterns = [
    path('sign/<str:target_class>', sign_signable_view),
]