"""Login, token, password and user/group endpoints."""

import base64
from datetime import timedelta

from django.conf import settings

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from wareApp import sendmail
from wareApp.models import OTP, User
from rest_framework.authtoken.models import Token

from wareApp.serializers import LoginSerializer, UserSerializer
from wareApp.utility import entryExit, logger


class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """

    User = get_user_model()
    queryset = User.objects.all().order_by("-date_joined")


class GroupViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Group.objects.all()


class LoginApi(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    @entryExit
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, created = Token.objects.get_or_create(user=user)
        userinfo = User.objects.get(id=token.user_id)
        serializer_class = UserSerializer(userinfo, many=False)
        return Response({"token": token.key, "user": serializer_class.data})


class ValidatedToken(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        token = data.get("token", "")
        if token:
            user = Token.objects.filter(key=token)
            if user:
                return Response({"result": "true"})
            else:
                return Response({"result": "false"})
        else:
            return Response(
                {"error": "invalid API Payload"}, status=status.HTTP_400_BAD_REQUEST
            )


class TokenViewSet(viewsets.ModelViewSet):
    pass


class ForgetPassword(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "password_reset"

    @entryExit
    def post(self, request):
        data = request.data
        username = data.get("Username", "")
        logger.debug("%s %s", "username : ", username)
        email = data.get("email", "")
        contact_number = data.get("mobile", "")
        try:
            if User.objects.filter(username=username):
                logger.debug("%s", "inside if")
                user = User.objects.get(username=username)
                logger.debug("%s %s", "user : ", user)
                if str(user.email) == str(email) and str(user.Contact_number) == str(
                    contact_number
                ):
                    logger.debug("%s", "###")
                    otp = sendmail.emailcheck(user.id, user.username, user.email)
                    body = {
                        "result": 1,
                        "msg": "Otp sent successfull . Kindly check your email ",
                    }
                    # The OTP proves the caller owns the e-mail address, so it is
                    # only sent by e-mail. PASSWORD_RESET_RETURN_OTP=True restores
                    # the old behaviour (OTP also in the response) for old clients.
                    if getattr(settings, "PASSWORD_RESET_RETURN_OTP", False):
                        body["otp"] = otp
                    return Response(body)
                else:
                    return Response({"result": 0, "msg": "Data is not valid"})
            else:
                return Response(
                    {"result": 0, "msg": "Username doesn't match in database"}
                )
        except Exception as err:
            logger.exception("Forgot password failed: username=%s", username)
            return Response(
                {"result": 0, "msg": "Error!!!!!!!!!", "error": type(err).__name__}
            )


class ResetPasswordApi(APIView):
    """Set a new password with the OTP from ``forgot/``.

    The OTP is valid for PASSWORD_RESET_OTP_MINUTES, works once, and must
    match exactly one user (optionally the given ``username``). Attempts are
    rate limited per client (``password_reset`` throttle scope).
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "password_reset"

    @entryExit
    def post(self, request):
        data = request.data
        otp = str(data.get("otp", "")).strip()
        new_password = data.get("newpassword", "")
        username = data.get("username") or data.get("Username")
        if not otp or not new_password:
            return Response(
                {"result": 0, "msg": "OTP doesn't match"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        valid_after = timezone.now() - timedelta(
            minutes=getattr(settings, "PASSWORD_RESET_OTP_MINUTES", 10)
        )
        codes = OTP.objects.filter(otp=otp, created__gte=valid_after)
        if username:
            codes = codes.filter(
                user_id__in=User.objects.filter(username=username).values("id")
            )
        user_ids = set(codes.values_list("user_id", flat=True))
        if len(user_ids) != 1:
            logger.warning("Password reset rejected: invalid or expired OTP")
            return Response(
                {"result": 0, "msg": "OTP doesn't match"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = User.objects.filter(id=user_ids.pop()).first()
        if user is None:
            return Response(
                {"result": 0, "msg": "OTP doesn't match"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new_password)
        user.save()
        # Single use: every code of this user is spent.
        OTP.objects.filter(user_id=user.id).delete()
        logger.info("Password reset: user_id=%s", user.id)
        return Response({"result": 1, "msg": "password reset successfully"})


class ChangePassword(APIView):
    permission_classes = [IsAuthenticated]

    @entryExit
    def post(self, request):
        data = request.data
        old_password = base64.b64decode(data.get("old_password", ""))  # Need to ask
        new_password = base64.b64decode(data.get("new_password", ""))  # Need to ask
        token = Token.objects.get(user=request.user)
        if authenticate(username=request.user.username, password=old_password):
            request.user.set_password(new_password)
            request.user.save()
            return Response({"result": 1, "msg": "Password changed successfully"})
        else:
            return Response(
                {"result": 0, "msg": "Invalid old password"},
                status=status.HTTP_400_BAD_REQUEST,
            )
