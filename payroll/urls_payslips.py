"""Everyone's own payslips. Kept outside /payroll/ so staff menus never link into the office payroll pages."""
from django.urls import path

from . import views

app_name = "payslips"

urlpatterns = [
    path("", views.MyPayslipListView.as_view(), name="mine"),
    path("<int:line>/", views.MyPayslipView.as_view(), name="detail"),
    path("<int:line>/payslip.pdf", views.MyPayslipView.as_view(), {"pdf": True}, name="pdf"),
]
