from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("settings/company/", views.CompanySettingsView.as_view(), name="company_settings"),
    path("files/<int:pk>/", views.AttachmentDownloadView.as_view(), name="file"),
    path("audit/", views.AuditLogView.as_view(), name="audit"),
    path("settings/company/logo/", views.LogoView.as_view(), name="logo"),
]
