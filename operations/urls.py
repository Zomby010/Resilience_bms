from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    path("sites/", views.SiteListView.as_view(), name="sites"),
    path("sites/<int:pk>/", views.SiteDetailView.as_view(), name="site_detail"),
    path("sites/<int:pk>/edit/", views.SiteEditView.as_view(), name="site_edit"),
    path("team-today/", views.TeamTodayView.as_view(), name="team_today"),
    path("ob/", views.OBListView.as_view(), name="ob"),
    path("ob/write/", views.OBWriteView.as_view(), name="ob_write"),
    path("ob/quick/<slug:code>/", views.OBQuickView.as_view(), name="ob_quick"),
    path("visits/", views.VisitListView.as_view(), name="visits"),
    path("visits/new/", views.VisitCreateView.as_view(), name="visit_create"),
    path("visits/<int:pk>/", views.VisitDetailView.as_view(), name="visit_detail"),
    path("equipment/", views.EquipmentView.as_view(), name="equipment"),
]
