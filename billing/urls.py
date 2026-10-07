from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.InvoiceListView.as_view(), name="list"),
    path("new/", views.InvoiceFormView.as_view(), name="create"),
    path("<int:pk>/", views.InvoiceDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.InvoiceFormView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.InvoiceDeleteView.as_view(), name="delete"),
    path("<int:pk>/send/", views.InvoiceSendView.as_view(), name="send"),
    path("<int:pk>/pdf/", views.InvoicePdfView.as_view(), name="pdf"),
    path("<int:pk>/print/", views.InvoicePrintView.as_view(), name="print"),
    path("<int:pk>/payments/new/", views.PaymentCreateView.as_view(), name="payment"),
    path("<int:pk>/cancel/", views.InvoiceCancelView.as_view(), name="cancel"),
]
