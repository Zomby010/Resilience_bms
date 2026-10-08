from django.urls import path

from . import views

app_name = "incidents"

urlpatterns = [
    path("", views.IncidentListView.as_view(), name="list"),
    path("new/", views.IncidentCreateView.as_view(), name="create"),
    path("<int:pk>/", views.IncidentDetailView.as_view(), name="detail"),
    path("<int:pk>/print/", views.IncidentPrintView.as_view(), name="print"),
    path("<int:pk>/note/", views.IncidentAction.as_view(action="add_note"), name="note"),
    path("<int:pk>/supervisor-review/", views.SupervisorReviewView.as_view(), name="supervisor_review"),
    path("<int:pk>/manager-review/", views.ManagerAction.as_view(action="manager_review"), name="manager_review"),
    path("<int:pk>/close/", views.OfficeAction.as_view(action="close"), name="close"),
    path("<int:pk>/reopen/", views.ManagerAction.as_view(action="reopen"), name="reopen"),
]
