from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("clients/", views.ClientListView.as_view(), name="list"),
    path("clients/new/", views.ClientCreateView.as_view(), name="create"),
    path("clients/<int:pk>/", views.ClientDetailView.as_view(), name="detail"),
    path("clients/<int:pk>/edit/", views.ClientUpdateView.as_view(), name="edit"),
    path("clients/<int:pk>/deactivate/", views.ClientActiveView.as_view(active=False), name="deactivate"),
    path("clients/<int:pk>/reactivate/", views.ClientActiveView.as_view(active=True), name="reactivate"),
    path("clients/<int:pk>/supervisor/", views.ClientSupervisorView.as_view(), name="supervisor"),
    path("clients/<int:pk>/sites/", views.ClientSitesView.as_view(), name="sites"),
    # messages
    path("clients/<int:pk>/messages/new/", views.MessageCreateView.as_view(), name="message_create"),
    path("clients/messages/<int:pk>/", views.MessageDetailView.as_view(), name="message_detail"),
    path("clients/messages/<int:pk>/edit/", views.MessageEditView.as_view(), name="message_edit"),
    path("clients/messages/<int:pk>/send/", views.MessageSendView.as_view(), name="message_send"),
    path("clients/messages/<int:pk>/told-by-phone/", views.MessageOfflineView.as_view(), name="message_offline"),
    # feedback
    path("clients/feedback/", views.FeedbackListView.as_view(), name="feedback_list"),
    path("clients/<int:pk>/feedback/new/", views.FeedbackCreateView.as_view(), name="feedback_create"),
    path("clients/feedback/<int:pk>/", views.FeedbackDetailView.as_view(), name="feedback_detail"),
    path("clients/feedback/<int:pk>/review/", views.FeedbackReviewView.as_view(), name="feedback_review"),
    path("clients/feedback/<int:pk>/respond/", views.FeedbackRespondView.as_view(), name="feedback_respond"),
    path("clients/feedback/<int:pk>/close/", views.FeedbackCloseView.as_view(), name="feedback_close"),
    path("clients/feedback/<int:pk>/make-issue/", views.FeedbackMakeIssueView.as_view(), name="feedback_make_issue"),
    # issues
    path("issues/", views.IssueListView.as_view(), name="issue_list"),
    path("issues/new/", views.IssueCreateView.as_view(), name="issue_create"),
    path("issues/<int:pk>/", views.IssueDetailView.as_view(), name="issue_detail"),
    path("issues/<int:pk>/note/", views.IssueNoteView.as_view(), name="issue_note"),
    path("issues/<int:pk>/status/", views.IssueStatusView.as_view(), name="issue_status"),
    path("issues/<int:pk>/assign/", views.IssueAssignView.as_view(), name="issue_assign"),
]
