import csv

from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.dateparse import parse_date
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.models import Role
from accounts.permissions import RoleRequiredMixin

from .forms import CategoryForm, ExpenseForm
from .models import Expense, ExpenseCategory, ExpenseLog

# The Secretary has full access to the tracker; the Manager may only look.
VIEW_ROLES = (Role.SECRETARY, Role.MANAGER)
EDIT_ROLES = (Role.SECRETARY,)


class ExpenseListView(RoleRequiredMixin, ListView):
    allowed_roles = VIEW_ROLES
    template_name = "finance/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 25

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
        date_from, date_to = parse_date(g.get("from", "")), parse_date(g.get("to", ""))
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def get_queryset(self):
        return self.get_filtered()

    def render_to_response(self, context, **kwargs):
        if self.request.GET.get("export") == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="expenditure.csv"'
            writer = csv.writer(response)
            writer.writerow(["Date", "Category", "Description", "Amount (KES)", "Reference", "Recorded by"])
            for e in self.get_filtered():
                # Prefix cells that spreadsheets would treat as formulas (CSV injection).
                desc = e.description
                if desc[:1] in ("=", "+", "-", "@"):
                    desc = "'" + desc
                writer.writerow([e.date, e.category.name, desc, e.amount, e.reference, e.recorded_by])
            return response
        return super().render_to_response(context, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filtered = self.get_filtered()
        ctx["total"] = filtered.aggregate(total=Sum("amount"))["total"] or 0
        ctx["by_category"] = (
            filtered.values("category__name").annotate(total=Sum("amount")).order_by("-total")[:6]
        )
        ctx["categories"] = ExpenseCategory.objects.all()
        ctx["can_edit"] = self.request.user.role in EDIT_ROLES
        g = self.request.GET
        ctx.update(q=g.get("q", ""), f_category=g.get("category", ""), f_from=g.get("from", ""), f_to=g.get("to", ""))
        params = g.copy()
        params.pop("page", None)
        ctx["query_string"] = params.urlencode()
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
        before = Expense.objects.get(pk=self.object.pk).snapshot()
        with transaction.atomic():
            response = super().form_valid(form)
            ExpenseLog.record(
                self.object, ExpenseLog.Action.UPDATED, self.request.user,
                details=f"{before}  ->  {self.object.snapshot()}",
            )
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


class HistoryView(RoleRequiredMixin, ListView):
    """Full expenditure history, including edits and deletions."""

    allowed_roles = VIEW_ROLES
    template_name = "finance/history.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_queryset(self):
        return ExpenseLog.objects.select_related("by")


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
