from django.urls import path, include
from .views import NewUserView, CustomTokenObtainPairView

urlpatterns = [
	path('vendor/onboard/<str:action>', NewUserView.as_view(), name='onboarding'),
	path('vendor/authenticate', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
]