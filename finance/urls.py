from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.ExpenseListView.as_view(), name="list"),
    path("new/", views.ExpenseCreateView.as_view(), name="create"),
    path("history/", views.HistoryView.as_view(), name="history"),
    path("categories/", views.CategoryView.as_view(), name="categories"),
    path("<int:pk>/", views.ExpenseDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ExpenseUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.ExpenseDeleteView.as_view(), name="delete"),
    path("approvals/", views.ApprovalsView.as_view(), name="approvals"),
    path("<int:pk>/approve/", views.DecideView.as_view(approve=True), name="approve"),
    path("<int:pk>/reject/", views.DecideView.as_view(approve=False), name="reject"),
]
