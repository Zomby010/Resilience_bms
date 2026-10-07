from django.urls import path

from . import views

app_name = "escalations"

urlpatterns = [
    path("", views.EscalationListView.as_view(), name="list"),
    path("new/", views.EscalationCreateView.as_view(), name="create"),
    path("<int:pk>/", views.EscalationDetailView.as_view(), name="detail"),
    path("<int:pk>/reply/", views.ReplyView.as_view(), name="reply"),
    path("<int:pk>/send-back/", views.EscalationAction.as_view(action="send_back"), name="send_back"),
    path("<int:pk>/resolve/", views.EscalationAction.as_view(action="resolve"), name="resolve"),
]
