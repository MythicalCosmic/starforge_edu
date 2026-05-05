from django.urls import path

from .views import JWTLogoutView, JWTRefreshView, OTPRequestView, OTPVerifyView

urlpatterns = [
    path("otp/request/", OTPRequestView.as_view(), name="otp-request"),
    path("otp/verify/", OTPVerifyView.as_view(), name="otp-verify"),
    path("refresh/", JWTRefreshView.as_view(), name="token-refresh"),
    path("logout/", JWTLogoutView.as_view(), name="token-logout"),
]
