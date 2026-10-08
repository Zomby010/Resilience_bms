from django.contrib import messages
from django.db.models import Count, F, Q
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from accounts.models import Role, User
from accounts.permissions import RoleRequiredMixin
from core.filters import apply_dates
from core.mixins import OFFICE, ActionView, CsvExportMixin, FilterContextMixin, OfficeRequiredMixin, csv_time
from core.models import AuditLog
from core.services import audit
from core.workflow import TransitionError

from . import services
from .forms import AdjustForm, ApproveForm, CategoryForm, ItemForm, NewItemForm, RequestForm, ReturnForm
from .models import Category, Item, ItemRequest

R = ItemRequest.Status
REQUESTERS = (Role.STAFF, Role.SUPERVISOR)


# --- item library (office) ------------------------------------------------------

class LibraryView(OfficeRequiredMixin, FilterContextMixin, ListView):
    template_name = "inventory/library.html"
    context_object_name = "items"
    paginate_by = 48

    def get_queryset(self):
        qs = Item.objects.select_related("category")
        g = self.request.GET
        qs = qs.filter(is_active=g.get("show") != "retired")
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
        if g.get("category", "").isdigit():
            qs = qs.filter(category_id=int(g["category"]))
        stock = g.get("stock")
        if stock == "low":
            qs = qs.filter(min_stock__gt=0, qty_available__lte=F("min_stock"))
        elif stock == "out":
            qs = qs.filter(qty_available=0)
        elif stock == "damaged":
            qs = qs.filter(qty_damaged__gt=0)
        elif stock == "out_with_people":
            qs = qs.filter(qty_issued__gt=0)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        active = Item.objects.filter(is_active=True)
        ctx.update(
            categories=Category.objects.filter(is_active=True),
            low_count=active.filter(min_stock__gt=0, qty_available__lte=F("min_stock")).count(),
            waiting=ItemRequest.objects.filter(status__in=(R.PENDING, R.RETURN_CLAIMED)).count(),
            overdue=services.overdue_requests().count(),
        )
        return ctx


class ItemCreateView(OfficeRequiredMixin, CreateView):
    form_class = NewItemForm
    template_name = "inventory/item_form.html"

    def form_valid(self, form):
        item = services.create_item(form.save(commit=False), form.cleaned_data["opening_qty"], self.request.user)
        messages.success(self.request, f"{item.name} added as {item.code}.")
        return redirect(item)


class ItemUpdateView(OfficeRequiredMixin, UpdateView):
    model = Item
    form_class = ItemForm
    template_name = "inventory/item_form.html"

    def form_valid(self, form):
        before = audit.snapshot(Item.objects.get(pk=self.object.pk), services.ITEM_FIELDS)
        item = services.update_item(form.save(commit=False), self.request.user, before)
        messages.success(self.request, "Item details saved.")
        return redirect(item)


class ItemDetailView(OfficeRequiredMixin, DetailView):
    model = Item
    template_name = "inventory/item_detail.html"
    context_object_name = "item"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        item = self.object
        ctx.update(
            movements=item.movements.select_related("by", "request__requester")[:50],
            open_requests=item.requests.filter(status__in=services.OPEN_REQUEST_STATUSES).select_related("requester"),
            adjust_form=AdjustForm(),
            history=AuditLog.objects.filter(entity_type="inventory.item", entity_id=str(item.pk)).select_related("actor")[:30],
            escalation=_open_escalation(item),
        )
        return ctx


class AdjustView(OfficeRequiredMixin, ActionView):
    model = Item

    def act(self, item):
        form = AdjustForm(self.request.POST)
        if not form.is_valid():
            raise TransitionError("Choose what happened, how many, and write the reason.")
        d = form.cleaned_data
        services.adjust_stock(item, d["action"], d["qty"], d["reason"], self.request.user)
        return f"Stock updated. {item.qty_available} now in the store."


class ItemActiveView(OfficeRequiredMixin, ActionView):
    model = Item
    active = False

    def act(self, item):
        services.set_item_active(item, self.active, self.request.user)
        return f"{item.name} {'is back in the library' if self.active else 'is retired. It is kept in the records.'}."


class CategoryView(OfficeRequiredMixin, CreateView):
    form_class = CategoryForm
    template_name = "inventory/categories.html"

    def get_success_url(self):
        return reverse("inventory:categories")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = Category.objects.annotate(n=Count("items"))
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Category added.")
        return super().form_valid(form)


class FlagsView(OfficeRequiredMixin, TemplateView):
    """D12: the Manager ticks the items that need his approval. The Secretary can only look."""

    template_name = "inventory/flags.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["items"] = Item.objects.filter(is_active=True).select_related("category", "flag_changed_by").order_by("category__name", "name")
        ctx["can_edit"] = self.request.user.role == Role.MANAGER
        ctx["waiting"] = ItemRequest.objects.filter(status=R.AWAITING_MANAGER).select_related("item", "requester")
        return ctx

    def post(self, request, *args, **kwargs):
        if request.user.role != Role.MANAGER:
            raise PermissionDenied
        ids = [int(x) for x in request.POST.getlist("flagged") if x.isdigit()]
        n = services.set_manager_flags(ids, request.user)
        messages.success(request, f"Saved. {n} item(s) changed." if n else "No changes.")
        return redirect("inventory:flags")


# --- requester pages (staff and supervisors) -------------------------------------------

class RequesterMixin(RoleRequiredMixin):
    allowed_roles = REQUESTERS


class BrowseView(RequesterMixin, FilterContextMixin, ListView):
    """Names only, with 'available' or 'out of stock'. No counts."""

    template_name = "inventory/browse.html"
    context_object_name = "items"
    paginate_by = 60

    def get_queryset(self):
        qs = Item.objects.filter(is_active=True).select_related("category")
        g = self.request.GET
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(category__name__icontains=q))
        if g.get("category", "").isdigit():
            qs = qs.filter(category_id=int(g["category"]))
        return qs.order_by("category__name", "name")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "categories": Category.objects.filter(is_active=True, items__is_active=True).distinct()}


class RequestCreateView(RequesterMixin, FormView):
    form_class = RequestForm
    template_name = "inventory/request_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.item = get_object_or_404(Item, pk=kwargs["item_id"], is_active=True)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "item": self.item}

    def form_valid(self, form):
        try:
            req = services.create_request(self.item, form.cleaned_data["qty"], form.cleaned_data["reason"], self.request.user)
        except TransitionError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return redirect("inventory:request_sent", pk=req.pk)


class RequestSentView(RequesterMixin, DetailView):
    template_name = "inventory/request_sent.html"
    context_object_name = "req"

    def get_queryset(self):
        return ItemRequest.objects.filter(requester=self.request.user).select_related("item")


class MyRequestsView(RequesterMixin, ListView):
    template_name = "inventory/my_requests.html"
    context_object_name = "reqs"
    paginate_by = 30

    def get_queryset(self):
        return ItemRequest.objects.filter(requester=self.request.user).select_related("item")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["with_me"] = ItemRequest.objects.filter(requester=self.request.user, status__in=(R.ISSUED, R.RETURN_CLAIMED),
                                                    item__returnable=True).select_related("item")
        return ctx


class MyRequestDetailView(RequesterMixin, DetailView):
    template_name = "inventory/my_request_detail.html"
    context_object_name = "req"

    def get_queryset(self):
        return ItemRequest.objects.filter(requester=self.request.user).select_related("item")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "steps": services.steps_for(self.object)}


class MyRequestAction(RequesterMixin, ActionView):
    def get_queryset(self):
        return ItemRequest.objects.filter(requester=self.request.user).select_related("item")

    def get_success_url(self):
        return reverse("inventory:mine_detail", args=[self.object.pk])


class MyCancelView(MyRequestAction):
    def act(self, req):
        services.cancel_by_requester(req, self.request.user)
        return "Your request is cancelled."


class MyReturnedView(MyRequestAction):
    def act(self, req):
        services.claim_return(req, self.request.user)
        return "Thank you. The Secretary will check the item and confirm the return."


# --- item requests (office) --------------------------------------------------------

class RequestListView(OfficeRequiredMixin, CsvExportMixin, FilterContextMixin, ListView):
    template_name = "inventory/request_list.html"
    context_object_name = "reqs"
    paginate_by = 30
    csv_filename = "item-requests.csv"
    csv_header = ["Asked", "Person", "Role", "Item code", "Item", "Qty asked", "Qty given", "Reason", "Status",
                  "Return by", "Returned good", "Returned damaged", "Lost"]

    def get_queryset(self):
        qs = ItemRequest.objects.select_related("item", "requester")
        g = self.request.GET
        status = g.get("status", "todo")
        if status == "todo":
            qs = qs.filter(status__in=(R.AWAITING_MANAGER, R.PENDING, R.READY, R.RETURN_CLAIMED))
        elif status == "out":
            qs = qs.filter(status__in=(R.ISSUED, R.RETURN_CLAIMED), item__returnable=True)
        elif status in R.values:
            qs = qs.filter(status=status)
        if g.get("requester", "").isdigit():
            qs = qs.filter(requester_id=int(g["requester"]))
        if g.get("item", "").isdigit():
            qs = qs.filter(item_id=int(g["item"]))
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(item__name__icontains=q) | Q(item__code__icontains=q) | Q(reason__icontains=q)
                           | Q(requester__first_name__icontains=q) | Q(requester__last_name__icontains=q)
                           | Q(requester__username__icontains=q))
        return apply_dates(qs, g, "created_at")

    def csv_rows(self, qs):
        for r in qs:
            yield [csv_time(r.created_at), r.requester, r.requester_role, r.item.code, r.item.name, r.qty_requested,
                   r.qty_issued or "", r.reason, r.get_status_display(), r.expected_return_date or "",
                   r.qty_returned_good, r.qty_returned_damaged, r.qty_lost]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(statuses=R.choices, status=self.request.GET.get("status", "todo"),
                   people=User.objects.filter(role__in=REQUESTERS).order_by("first_name", "username"))
        return ctx


class OverdueView(OfficeRequiredMixin, ListView):
    template_name = "inventory/overdue.html"
    context_object_name = "reqs"

    def get_queryset(self):
        return services.overdue_requests().order_by("expected_return_date")


class RequestDetailView(OfficeRequiredMixin, DetailView):
    template_name = "inventory/request_detail.html"
    context_object_name = "req"

    def get_queryset(self):
        return ItemRequest.objects.select_related("item", "requester", "decided_by", "manager_decided_by",
                                                  "handed_over_by", "return_approved_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        req = self.object
        own = req.requester_id == self.request.user.pk
        ctx.update(
            own=own, approve_form=ApproveForm(req=req), return_form=ReturnForm(initial={"good": req.qty_issued or 0}),
            movements=req.movements.select_related("by"),
            history=AuditLog.objects.filter(entity_type="inventory.itemrequest", entity_id=str(req.pk)).select_related("actor"),
            is_overdue=bool(req.item.returnable and req.expected_return_date and req.status in (R.ISSUED, R.RETURN_CLAIMED)
                            and req.expected_return_date < timezone.localdate()),
        )
        return ctx


class OfficeRequestAction(OfficeRequiredMixin, ActionView):
    def get_queryset(self):
        return ItemRequest.objects.select_related("item", "requester")

    def text(self, name):
        return self.request.POST.get(name, "")


class ManagerDecideView(OfficeRequestAction):
    allowed_roles = (Role.MANAGER,)
    approve = True

    def act(self, req):
        services.manager_decide(req, self.request.user, self.approve, self.text("reason"))
        return "Approved. The Secretary has been told." if self.approve else "Request rejected. The person has been told."


class ApproveView(OfficeRequestAction):
    def act(self, req):
        form = ApproveForm(self.request.POST, req=req)
        if not form.is_valid():
            raise TransitionError(" ".join(e for errs in form.errors.values() for e in errs))
        d = form.cleaned_data
        services.approve_request(req, self.request.user, d["qty"], d.get("expected_return_date"), d["hand_over_now"])
        if d["hand_over_now"]:
            return f"Handed over {d['qty']} x {req.item.name} to {req.requester}."
        return f"Approved. {d['qty']} x {req.item.name} kept aside for {req.requester} to collect."


class RejectView(OfficeRequestAction):
    def act(self, req):
        services.reject_request(req, self.request.user, self.text("reason"))
        return "Request rejected. The person has been told."


class HandoverView(OfficeRequestAction):
    def act(self, req):
        services.hand_over(req, self.request.user)
        return f"Handed over to {req.requester}."


class CancelApprovalView(OfficeRequestAction):
    def act(self, req):
        services.cancel_approval(req, self.request.user, self.text("reason"))
        return "Cancelled. The item is back in the store."


class ApproveReturnView(OfficeRequestAction):
    """Only the Secretary/Manager, and never on their own request (403 for everyone else via the mixin)."""

    def act(self, req):
        form = ReturnForm(self.request.POST)
        if not form.is_valid():
            raise TransitionError("Enter how many came back good, damaged and lost.")
        d = form.cleaned_data
        services.approve_return(req, self.request.user, d["good"], d["damaged"], d["lost"], d["notes"])
        return "Return confirmed and stock updated."


class NotReceivedView(OfficeRequestAction):
    def act(self, req):
        services.not_received(req, self.request.user, self.text("note"))
        return "Marked as not received. The person has been told it is still with them."


class RemindView(OfficeRequestAction):
    def act(self, req):
        services.remind(req, self.request.user)
        return f"Reminder sent to {req.requester}."


def _open_escalation(obj):
    from escalations.services import open_escalation

    return open_escalation(obj)

