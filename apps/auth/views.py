from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenBlacklistView

from apps.users.services import register_device
from core.utils import client_ip, user_agent

from . import services
from .serializers import (
    OTPRequestSerializer,
    OTPVerifySerializer,
    RefreshSerializer,
    TokenPairSerializer,
)
from .throttles import OTPGlobalThrottle, OTPIPThrottle, OTPPhoneThrottle


class OTPRequestView(APIView):
    """POST /api/v1/auth/otp/request/  body: {identifier}"""

    permission_classes = [AllowAny]
    throttle_classes = [OTPPhoneThrottle, OTPIPThrottle, OTPGlobalThrottle]

    @extend_schema(
        summary="Request a login OTP",
        request=OTPRequestSerializer,
        responses={
            202: OpenApiResponse(description="OTP dispatched."),
            429: OpenApiResponse(description="throttled envelope"),
        },
        tags=["auth"],
    )
    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.send_otp(
            identifier=serializer.validated_data["identifier"],
            ip=client_ip(request),
            user_agent=user_agent(request),
        )
        return Response(status=status.HTTP_202_ACCEPTED)


class OTPVerifyView(APIView):
    """POST /api/v1/auth/otp/verify/  body: {identifier, code, device_id?, platform?}"""

    permission_classes = [AllowAny]
    throttle_classes = [OTPPhoneThrottle, OTPIPThrottle]

    @extend_schema(
        summary="Verify an OTP and receive a JWT pair",
        request=OTPVerifySerializer,
        responses={
            200: TokenPairSerializer,
            400: OpenApiResponse(description="validation_error / user_not_found envelope"),
        },
        tags=["auth"],
    )
    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ua = user_agent(request)
        user = services.verify_otp(
            identifier=data["identifier"],
            code=data["code"],
            ip=client_ip(request),
            user_agent=ua,
        )
        register_device(
            user=user,
            device_id=data.get("device_id", ""),
            platform=data.get("platform", ""),
            user_agent=ua,
        )
        return Response(services.issue_token_pair(user))


class JWTRefreshView(APIView):
    """POST /api/v1/auth/refresh/  body: {refresh}  -> {access, refresh}

    Rotates the refresh token (the old one is blacklisted) and re-stamps the
    TD-1 claims onto the new pair. Replaying a blacklisted token revokes all of
    the user's sessions (401 `refresh_reused`).
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Rotate a refresh token",
        request=RefreshSerializer,
        responses={
            200: TokenPairSerializer,
            401: OpenApiResponse(description="authentication_failed / refresh_reused envelope"),
        },
        tags=["auth"],
    )
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pair = services.rotate_refresh_token(serializer.validated_data["refresh"])
        return Response(pair)


class JWTLogoutView(TokenBlacklistView):
    """POST /api/v1/auth/logout/  body: {refresh}  -> 200

    Blacklists a single refresh token (this device).
    """


class LogoutAllView(APIView):
    """POST /api/v1/auth/logout-all/  -> 204

    Revokes every session: blacklists all of the user's refresh tokens and bumps
    `token_version` so live access tokens are rejected too (D1-LC-8).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Log out of every device",
        request=None,
        responses={204: OpenApiResponse(description="All sessions revoked.")},
        tags=["auth"],
    )
    def post(self, request):
        services.logout_everywhere(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
