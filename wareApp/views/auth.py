"""Login, token, password and user/group endpoints."""

import base64

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from wareApp import sendmail
from wareApp.models import OTP, User
from wareApp.serializers import LoginSerializer, Token, UserSerializer
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
        logger.debug(request.data)
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
        logger.debug(request.data)
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

    @entryExit
    def post(self, request):
        data = request.data
        logger.debug("%s %s", "data : ", data)
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
                    return Response(
                        {
                            "result": 1,
                            "msg": "Otp sent successfull . Kindly check your email ",
                            "otp": otp,
                        }
                    )
                else:
                    return Response({"result": 0, "msg": "Data is not valid"})
            else:
                return Response(
                    {"result": 0, "msg": "Username doesn't match in database"}
                )
        except Exception as err:
            return Response({"result": 0, "msg": "Error!!!!!!!!!", "error": err})


class ResetPasswordApi(APIView):
    permission_classes = [AllowAny]

    @entryExit
    def post(self, request):
        data = request.data
        otp = str(data.get("otp", ""))
        new_password = data.get("newpassword", "")
        try:
            ide = OTP.objects.get(otp=otp).user_id
            user = User.objects.get(id=ide)
            user.set_password(new_password)
            user.save()
            return Response({"result": 1, "msg": "password reset successfully"})
        except OTP.DoesNotExist:
            logger.error("OTP:{otp} is not available")
            return Response(
                {"result": 0, "msg": "OTP doesn't match"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as err:
            logger.critical(err)
            return Response(
                {"result": 0, "msg": "API Error"}, status=status.HTTP_400_BAD_REQUEST
            )


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
