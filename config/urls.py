from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("reports/", include("reports.urls")),
    path("finance/", include("finance.urls")),
    path("location/", include("tracking.urls")),
    path("notifications/", include("notifications.urls")),
    path("invoices/", include("billing.urls")),
    path("payroll/", include("payroll.urls")),
    path("escalations/", include("escalations.urls")),
    path("leave/", include("leave.urls")),
    path("attendance/", include("attendance.urls")),
    path("operations/", include("operations.urls")),
    path("", include("clients.urls")),
    path("", include("inventory.urls")),
    path("", include("core.urls")),
]
