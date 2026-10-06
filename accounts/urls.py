from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html", redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/password_change.html", success_url=reverse_lazy("accounts:profile")
        ),
        name="password_change",
    ),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("team/", views.TeamListView.as_view(), name="team"),
    path("team/new/", views.UserCreateView.as_view(), name="user_create"),
    path("team/<int:pk>/edit/", views.UserUpdateView.as_view(), name="user_edit"),
]
