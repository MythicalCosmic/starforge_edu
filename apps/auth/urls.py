from django.urls import path

from .views import (
    JWTLogoutView,
    JWTRefreshView,
    LoginView,
    LogoutAllView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("password/change/", PasswordChangeView.as_view(), name="password-change"),
    path("password/reset/request/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("refresh/", JWTRefreshView.as_view(), name="token-refresh"),
    path("logout/", JWTLogoutView.as_view(), name="token-logout"),
    path("logout-all/", LogoutAllView.as_view(), name="logout-all"),
]
