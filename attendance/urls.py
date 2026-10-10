from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.MyAttendanceView.as_view(), name="mine"),
    path("api/sign-in/", views.api_sign_in, name="api_sign_in"),
    path("sign-in/no-location/", views.SignInWithoutLocationView.as_view(), name="sign_in_no_location"),
    path("api/sign-out/<int:pk>/", views.api_sign_out, name="api_sign_out"),
    path("sign-out/<int:pk>/no-location/", views.SignOutWithoutLocationView.as_view(), name="sign_out_no_location"),
    path("team/", views.TeamView.as_view(), name="team"),
    path("day/", views.DaySheetView.as_view(), name="day"),
    path("records/", views.RecordListView.as_view(), name="records"),
    path("records/<int:pk>/approve/", views.RecordActionView.as_view(action="approve"), name="approve"),
    path("records/<int:pk>/reject/", views.RecordActionView.as_view(action="reject"), name="reject"),
    path("approve-all/", views.ApproveAllView.as_view(), name="approve_all"),
    path("mark/<int:user_pk>/", views.MarkView.as_view(), name="mark"),
    path("complete/", views.CompleteDayView.as_view(), name="complete"),
    path("reopen/", views.ReopenDayView.as_view(), name="reopen"),
]
