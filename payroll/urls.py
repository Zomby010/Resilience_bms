from django.urls import path

from . import views

app_name = "payroll"

urlpatterns = [
    path("", views.RunListView.as_view(), name="list"),
    path("profiles/", views.ProfileListView.as_view(), name="profiles"),
    path("profiles/<int:user_id>/", views.ProfileEditView.as_view(), name="profile_edit"),
    path("new/", views.RunCreateView.as_view(), name="create"),
    path("<int:pk>/", views.RunDetailView.as_view(), name="detail"),
    path("<int:pk>/lines/<int:line>/edit/", views.LineEditView.as_view(), name="line_edit"),
    path("<int:pk>/lines/<int:line>/remove/", views.RemoveLineView.as_view(), name="line_remove"),
    path("<int:pk>/add-person/", views.AddPersonView.as_view(), name="add_person"),
    path("<int:pk>/submit/", views.SubmitView.as_view(), name="submit"),
    path("<int:pk>/request-changes/", views.ManagerAction.as_view(action="request_changes"), name="request_changes"),
    path("<int:pk>/approve/", views.ManagerAction.as_view(action="approve"), name="approve"),
    path("<int:pk>/reject/", views.ManagerAction.as_view(action="reject"), name="reject"),
    path("<int:pk>/reopen/", views.ManagerAction.as_view(action="reopen"), name="reopen"),
    path("<int:pk>/export.csv", views.ExportCsvView.as_view(), name="export"),
    path("<int:pk>/print/", views.PrintView.as_view(), name="print"),
]
