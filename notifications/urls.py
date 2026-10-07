from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.InboxView.as_view(), name="inbox"),
    path("<int:pk>/open/", views.OpenView.as_view(), name="open"),
    path("read-all/", views.ReadAllView.as_view(), name="read_all"),
]
