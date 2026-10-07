from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    # item library (Secretary, Manager)
    path("inventory/", views.LibraryView.as_view(), name="library"),
    path("inventory/new/", views.ItemCreateView.as_view(), name="create"),
    path("inventory/categories/", views.CategoryView.as_view(), name="categories"),
    path("inventory/manager-approval/", views.FlagsView.as_view(), name="flags"),
    path("inventory/<int:pk>/", views.ItemDetailView.as_view(), name="detail"),
    path("inventory/<int:pk>/edit/", views.ItemUpdateView.as_view(), name="edit"),
    path("inventory/<int:pk>/adjust/", views.AdjustView.as_view(), name="adjust"),
    path("inventory/<int:pk>/deactivate/", views.ItemActiveView.as_view(active=False), name="deactivate"),
    path("inventory/<int:pk>/reactivate/", views.ItemActiveView.as_view(active=True), name="reactivate"),
    # staff and supervisors
    path("items/", views.BrowseView.as_view(), name="browse"),
    path("items/<int:item_id>/request/", views.RequestCreateView.as_view(), name="request_new"),
    path("items/sent/<int:pk>/", views.RequestSentView.as_view(), name="request_sent"),
    path("items/mine/", views.MyRequestsView.as_view(), name="mine"),
    path("items/mine/<int:pk>/", views.MyRequestDetailView.as_view(), name="mine_detail"),
    path("items/mine/<int:pk>/cancel/", views.MyCancelView.as_view(), name="mine_cancel"),
    path("items/mine/<int:pk>/returned/", views.MyReturnedView.as_view(), name="mine_returned"),
    # item requests (Secretary, Manager)
    path("item-requests/", views.RequestListView.as_view(), name="request_list"),
    path("item-requests/overdue/", views.OverdueView.as_view(), name="overdue"),
    path("item-requests/<int:pk>/", views.RequestDetailView.as_view(), name="request_detail"),
    path("item-requests/<int:pk>/manager-approve/", views.ManagerDecideView.as_view(approve=True), name="manager_approve"),
    path("item-requests/<int:pk>/manager-reject/", views.ManagerDecideView.as_view(approve=False), name="manager_reject"),
    path("item-requests/<int:pk>/approve/", views.ApproveView.as_view(), name="approve"),
    path("item-requests/<int:pk>/reject/", views.RejectView.as_view(), name="reject"),
    path("item-requests/<int:pk>/handover/", views.HandoverView.as_view(), name="handover"),
    path("item-requests/<int:pk>/cancel-approval/", views.CancelApprovalView.as_view(), name="cancel_approval"),
    path("item-requests/<int:pk>/approve-return/", views.ApproveReturnView.as_view(), name="approve_return"),
    path("item-requests/<int:pk>/not-received/", views.NotReceivedView.as_view(), name="not_received"),
    path("item-requests/<int:pk>/remind/", views.RemindView.as_view(), name="remind"),
]
