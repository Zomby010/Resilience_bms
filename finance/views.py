from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.models import Role
from accounts.permissions import RoleRequiredMixin

from core.filters import apply_dates, query_string
from core.mixins import ActionView, CsvExportMixin, FilterContextMixin, csv_time
from core.services.files import attachments_for, save_attachment

from . import services
from .forms import CategoryForm, ExpenseForm
from .models import Expense, ExpenseCategory, ExpenseLog

# The Secretary has full access to the tracker; the Manager may only look.
VIEW_ROLES = (Role.SECRETARY, Role.MANAGER)
EDIT_ROLES = (Role.SECRETARY,)


class ExpenseListView(RoleRequiredMixin, CsvExportMixin, ListView):
    allowed_roles = VIEW_ROLES
    template_name = "finance/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 25
    csv_filename = "expenditure.csv"
    csv_header = ["Date", "Category", "Description", "Amount (KES)", "Reference", "Status", "Recorded by"]

    def get_filtered(self):
        qs = Expense.objects.select_related("category", "recorded_by")
        g = self.request.GET
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(description__icontains=q) | Q(reference__icontains=q) | Q(category__name__icontains=q)
            )
        if g.get("category", "").isdigit():
            qs = qs.filter(category_id=int(g["category"]))
        return apply_dates(qs, g, "date")

    def get_queryset(self):
        return self.get_filtered()

    def csv_rows(self, qs):
        for e in qs:
            yield [e.date, e.category.name, e.description, e.amount, e.reference, e.get_status_display(), e.recorded_by]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Expenses waiting for (or refused) Manager approval are listed but left out of totals.
        filtered = self.get_filtered().filter(status=Expense.Status.RECORDED)
        ctx["total"] = filtered.aggregate(total=Sum("amount"))["total"] or 0
        ctx["by_category"] = (
            filtered.values("category__name").annotate(total=Sum("amount")).order_by("-total")[:6]
        )
        ctx["categories"] = ExpenseCategory.objects.all()
        ctx["can_edit"] = self.request.user.role in EDIT_ROLES
        g = self.request.GET
        # One Expenses page: the list, or the same filtered expenses added up per month.
        ctx["view"] = "month" if g.get("view") == "month" else "list"
        if ctx["view"] == "month":
            ctx["months"] = (filtered.annotate(month=TruncMonth("date")).values("month")
                             .annotate(total=Sum("amount"), n=Count("id")).order_by("-month"))
        ctx.update(q=g.get("q", ""), f_category=g.get("category", ""), f_from=g.get("from", ""), f_to=g.get("to", ""))
        ctx["query_string"] = query_string(self.request)
        return ctx


class ExpenseDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = VIEW_ROLES
    model = Expense
    template_name = "finance/expense_detail.html"
    context_object_name = "expense"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["log"] = self.object.log.select_related("by")
        ctx["can_edit"] = self.request.user.role in EDIT_ROLES
        ctx["files"] = attachments_for(self.object)
        return ctx


class ExpenseCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = EDIT_ROLES
    form_class = ExpenseForm
    template_name = "finance/expense_form.html"

    def form_valid(self, form):
        form.instance.recorded_by = self.request.user
        with transaction.atomic():
            response = super().form_valid(form)
            ExpenseLog.record(self.object, ExpenseLog.Action.CREATED, self.request.user)
            if form.cleaned_data.get("receipt"):
                save_attachment(self.object, form.cleaned_data["receipt"], self.request.user)
            services.after_save(self.object, self.request.user)
        if self.object.status == Expense.Status.AWAITING_APPROVAL:
            messages.warning(self.request, "Expense recorded. It is above the approval limit, so it waits for the Manager.")
        else:
            messages.success(self.request, "Expense recorded.")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Record an expense"
        ctx["has_categories"] = ExpenseCategory.objects.exists()
        return ctx


class ExpenseUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = EDIT_ROLES
    model = Expense
    form_class = ExpenseForm
    template_name = "finance/expense_form.html"

    def form_valid(self, form):
        old = Expense.objects.get(pk=self.object.pk)
        before = old.snapshot()
        with transaction.atomic():
            response = super().form_valid(form)
            ExpenseLog.record(
                self.object, ExpenseLog.Action.UPDATED, self.request.user,
                details=f"{before}  ->  {self.object.snapshot()}",
            )
            if form.cleaned_data.get("receipt"):
                save_attachment(self.object, form.cleaned_data["receipt"], self.request.user)
            services.after_save(self.object, self.request.user, old_amount=old.amount)
        messages.success(self.request, "Expense updated.")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Edit expense"
        ctx["has_categories"] = True
        return ctx


class ExpenseDeleteView(RoleRequiredMixin, DeleteView):
    allowed_roles = EDIT_ROLES
    model = Expense
    template_name = "finance/expense_confirm_delete.html"
    success_url = reverse_lazy("finance:list")

    def form_valid(self, form):
        expense = self.object
        with transaction.atomic():
            ExpenseLog.record(expense, ExpenseLog.Action.DELETED, self.request.user)
            number = expense.pk
            response = super().form_valid(form)
        messages.success(self.request, f"Expense #{number} deleted (kept in the history).")
        return response


class HistoryView(RoleRequiredMixin, CsvExportMixin, FilterContextMixin, ListView):
    """Full expenditure history, including edits and deletions."""

    allowed_roles = VIEW_ROLES
    template_name = "finance/history.html"
    context_object_name = "entries"
    paginate_by = 50
    csv_filename = "expenditure-history.csv"
    csv_header = ["When", "Action", "Expense no.", "By", "Details"]

    def get_queryset(self):
        qs = ExpenseLog.objects.select_related("by", "expense")
        g = self.request.GET
        if g.get("action") in ExpenseLog.Action.values:
            qs = qs.filter(action=g["action"])
        q = (g.get("q") or "").strip().lstrip("#")
        if q:
            cond = Q(details__icontains=q)
            if q.isdigit():
                cond |= Q(expense_number=int(q))
            qs = qs.filter(cond)
        return apply_dates(qs, g, "at")

    def csv_rows(self, qs):
        for e in qs:
            yield [csv_time(e.at), e.get_action_display(), e.expense_number, e.by, e.details]

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "actions": ExpenseLog.Action.choices}


class CategoryView(RoleRequiredMixin, CreateView):
    allowed_roles = EDIT_ROLES
    form_class = CategoryForm
    template_name = "finance/categories.html"
    success_url = reverse_lazy("finance:categories")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = ExpenseCategory.objects.all()
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Category added.")
        return super().form_valid(form)


class ApprovalsView(RoleRequiredMixin, ListView):
    """Expenses above the limit, waiting for the Manager (owner decision D9)."""

    allowed_roles = (Role.MANAGER,)
    template_name = "finance/approvals.html"
    context_object_name = "expenses"

    def get_queryset(self):
        return Expense.objects.filter(status=Expense.Status.AWAITING_APPROVAL).select_related("category", "recorded_by")


class DecideView(ActionView):
    allowed_roles = (Role.MANAGER,)
    model = Expense
    approve = True

    def act(self, expense):
        services.decide(expense, self.request.user, self.approve, self.request.POST.get("note", ""))
        return "Expense approved." if self.approve else "Expense rejected. The Secretary has been told."
