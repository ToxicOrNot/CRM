from django.contrib.auth.views import LogoutView
from django.urls import path

from apps.accounts.views import UserSelectLoginView


urlpatterns = [
    path("login/", UserSelectLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
