from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("users/", views.UserListView.as_view(), name="users"),
    path("users/<str:personal_id>/promote/", views.PromoteUserView.as_view(), name="promote-user"),
    path("users/<str:personal_id>/demote/", views.DemoteUserView.as_view(), name="demote-user"),
]
