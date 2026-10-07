from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("reports/", include("reports.urls")),
    path("finance/", include("finance.urls")),
    path("location/", include("tracking.urls")),
    path("", include("core.urls")),
]
