from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .permissions import IsEditorOrAdmin
from .serializers import LoginSerializer, RegisterSerializer, UserSerializer

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("refresh")
        if not token:
            return Response({"detail": "חסר refresh token."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(token).blacklist()
        except TokenError:
            return Response({"detail": "טוקן לא תקין."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserListView(generics.ListAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsEditorOrAdmin]
    queryset = User.objects.all().order_by("personal_id")


class PromoteUserView(APIView):
    permission_classes = [IsEditorOrAdmin]

    def post(self, request, personal_id):
        user = get_object_or_404(User, personal_id=personal_id)
        user.role = User.Role.EDITOR
        user.save(update_fields=["role"])
        return Response(UserSerializer(user).data)


class DemoteUserView(APIView):
    permission_classes = [IsEditorOrAdmin]

    def post(self, request, personal_id):
        user = get_object_or_404(User, personal_id=personal_id)
        if user.is_superuser or user.role == User.Role.ADMIN:
            return Response({"detail": "לא ניתן להוריד הרשאות ממנהל."}, status=status.HTTP_400_BAD_REQUEST)
        user.role = User.Role.USER
        user.save(update_fields=["role"])
        return Response(UserSerializer(user).data)
