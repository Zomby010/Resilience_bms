from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("", views.MyLocationView.as_view(), name="mine"),
    path("api/me/", views.api_me, name="api_me"),
    path("api/start/", views.api_start, name="api_start"),
    path("api/stop/", views.api_stop, name="api_stop"),
    path("api/update/", views.api_update, name="api_update"),
    path("api/overview/", views.api_overview, name="api_overview"),
    path("tracker/", views.TrackerView.as_view(), name="tracker"),
    path("sites/", views.SiteListView.as_view(), name="sites"),
    path("sites/new/", views.SiteEditView.as_view(), name="site_create"),
    path("sites/<int:pk>/", views.SiteEditView.as_view(), name="site_edit"),
    path("people/", views.PeopleView.as_view(), name="people"),
    path("people/<int:pk>/", views.PersonEditView.as_view(), name="person_edit"),
    path("history/", views.HistoryView.as_view(), name="history"),
]
