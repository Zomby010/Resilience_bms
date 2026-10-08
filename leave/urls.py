from django.urls import path

from . import views

app_name = "leave"

urlpatterns = [
    path("", views.MyLeaveView.as_view(), name="mine"),
    path("ask/", views.AskView.as_view(), name="ask"),
    path("requests/", views.RequestListView.as_view(), name="request_list"),
    path("requests/<int:pk>/", views.RequestDetailView.as_view(), name="request_detail"),
    path("requests/<int:pk>/approve/", views.RequestAction.as_view(action="approve"), name="approve"),
    path("requests/<int:pk>/reject/", views.RequestAction.as_view(action="reject"), name="reject"),
    path("requests/<int:pk>/cancel/", views.RequestAction.as_view(action="cancel"), name="cancel"),
    path("days/", views.AllowanceListView.as_view(), name="allowances"),
    path("days/<int:pk>/", views.AllowanceEditView.as_view(), name="allowance_edit"),
    path("sick/", views.SickListView.as_view(), name="sick_list"),
    path("sick/report/", views.ReportSickView.as_view(), name="sick_report"),
    path("sick/<int:pk>/", views.SickDetailView.as_view(), name="sick_detail"),
    path("sick/<int:pk>/sheet/", views.SickAction.as_view(action="sheet"), name="sick_sheet"),
    path("sick/<int:pk>/last-day/", views.SickAction.as_view(action="last_day"), name="sick_last_day"),
    path("sick/<int:pk>/accept/", views.SickAction.as_view(action="accept"), name="sick_accept"),
    path("sick/<int:pk>/reject/", views.SickAction.as_view(action="reject"), name="sick_reject"),
    path("sick/<int:pk>/again/", views.SickAction.as_view(action="again"), name="sick_again"),
    path("sick/sheets/<int:pk>/", views.SickNoteDownloadView.as_view(), name="sheet"),
]
