from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.services import register_device
from core.permissions import DenyWriteForReadOnlyToken
from core.utils import client_ip, user_agent

from . import services
from .serializers import (
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    TokenSerializer,
)
from .throttles import (
    LoginIPThrottle,
    LoginUserThrottle,
    OTPGlobalThrottle,
    OTPIdentifierThrottle,
    OTPIPThrottle,
    OTPVerifyThrottle,
)


class LoginView(APIView):
    """POST /api/v1/auth/login/  body: {username, password, device_id?, platform?}"""

    permission_classes = [AllowAny]
    throttle_classes = [LoginUserThrottle, LoginIPThrottle]

    @extend_schema(
        summary="Log in with username and password",
        request=LoginSerializer,
        responses={
            200: TokenSerializer,
            401: OpenApiResponse(description="invalid_credentials envelope"),
            429: OpenApiResponse(description="throttled envelope"),
        },
        tags=["auth"],
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ua = user_agent(request)
        user = services.login_with_password(
            username=data["username"],
            password=data["password"],
            ip=client_ip(request),
            user_agent=ua,
        )
        register_device(
            user=user,
            device_id=data.get("device_id", ""),
            platform=data.get("platform", ""),
            user_agent=ua,
        )
        return Response(services.issue_token(user))


class PasswordChangeView(APIView):
    """POST /api/v1/auth/password/change/  body: {old_password, new_password}

    Ends every other session (bumps `tv`) and returns a fresh access token so
    THIS device stays logged in.
    """

    permission_classes = [IsAuthenticated, DenyWriteForReadOnlyToken]

    @extend_schema(
        summary="Change password (ends all other sessions)",
        request=PasswordChangeSerializer,
        responses={
            200: TokenSerializer,
            400: OpenApiResponse(description="wrong_password / weak_password envelope"),
        },
        tags=["auth"],
    )
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = services.change_password(
            user=request.user,
            old_password=serializer.validated_data["old_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(token)


class PasswordResetRequestView(APIView):
    """POST /api/v1/auth/password/reset/request/  body: {identifier}

    Always 202 — whether or not an account matches (anti-enumeration). The
    code goes to the phone/email ON FILE for the account.
    """

    permission_classes = [AllowAny]
    throttle_classes = [OTPIdentifierThrottle, OTPIPThrottle, OTPGlobalThrottle]

    @extend_schema(
        summary="Request a password-reset code",
        request=PasswordResetRequestSerializer,
        responses={
            202: OpenApiResponse(description="Reset code dispatched if the account exists."),
            429: OpenApiResponse(description="throttled envelope (Retry-After set)"),
        },
        tags=["auth"],
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(
            identifier=serializer.validated_data["identifier"],
            ip=client_ip(request),
            user_agent=user_agent(request),
        )
        return Response(status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(APIView):
    """POST /api/v1/auth/password/reset/confirm/  body: {identifier, code, new_password}

    On success every session is ended; the user logs in fresh.
    """

    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyThrottle, OTPIPThrottle]

    @extend_schema(
        summary="Confirm a password reset with the received code",
        request=PasswordResetConfirmSerializer,
        responses={
            204: OpenApiResponse(description="Password reset; all sessions ended."),
            400: OpenApiResponse(description="validation_error / weak_password envelope"),
            429: OpenApiResponse(description="throttled envelope"),
        },
        tags=["auth"],
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.reset_password(
            identifier=data["identifier"],
            code=data["code"],
            new_password=data["new_password"],
            ip=client_ip(request),
            user_agent=user_agent(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutView(APIView):
    """POST /api/v1/auth/logout/  -> 204

    Single-token auth: revokes every session for the caller by bumping
    `token_version`, so the live access token (and any other) is rejected on the
    next request. Requires the caller's own (full-scope) access token."""

    permission_classes = [IsAuthenticated, DenyWriteForReadOnlyToken]

    @extend_schema(
        summary="Log out (revoke all of the caller's sessions)",
        request=None,
        responses={204: OpenApiResponse(description="All sessions revoked.")},
        tags=["auth"],
    )
    def post(self, request):
        services.logout_everywhere(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
