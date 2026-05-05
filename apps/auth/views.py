from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView

from . import services
from .serializers import OTPRequestSerializer, OTPVerifySerializer, TokenPairSerializer
from .throttles import OTPGlobalThrottle, OTPIPThrottle, OTPPhoneThrottle


class OTPRequestView(APIView):
    """POST /api/v1/auth/otp/request/  body: {identifier}"""

    permission_classes = [AllowAny]
    throttle_classes = [OTPPhoneThrottle, OTPIPThrottle, OTPGlobalThrottle]

    @extend_schema(
        request=OTPRequestSerializer,
        responses={202: OpenApiResponse(description="OTP dispatched.")},
    )
    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.send_otp(identifier=serializer.validated_data["identifier"])
        return Response(status=status.HTTP_202_ACCEPTED)


class OTPVerifyView(APIView):
    """POST /api/v1/auth/otp/verify/  body: {identifier, code}  -> {access, refresh}"""

    permission_classes = [AllowAny]
    throttle_classes = [OTPPhoneThrottle, OTPIPThrottle]

    @extend_schema(
        request=OTPVerifySerializer,
        responses={200: TokenPairSerializer},
    )
    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.verify_otp(
            identifier=serializer.validated_data["identifier"],
            code=serializer.validated_data["code"],
        )
        pair = services.issue_token_pair(user)
        return Response(pair)


class JWTRefreshView(TokenRefreshView):
    """POST /api/v1/auth/refresh/  body: {refresh}  -> {access[, refresh]}"""


class JWTLogoutView(TokenBlacklistView):
    """POST /api/v1/auth/logout/  body: {refresh}  -> 200

    Adds the refresh token to the blacklist; subsequent rotations fail.
    """
