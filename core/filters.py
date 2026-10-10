"""Shared list helpers: date-range filters, day/week/month periods and safe CSV downloads."""
import csv
from datetime import datetime, timedelta

from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

PERIODS = (("day", "Today"), ("week", "This week"), ("month", "This month"))


def date_range(params):
    """(from, to) dates from ?from=YYYY-MM-DD&to=YYYY-MM-DD; either may be None."""
    return parse_date(params.get("from", "") or ""), parse_date(params.get("to", "") or "")


def apply_dates(qs, params, field):
    """Filter `qs` on a date or datetime `field` using ?from= and ?to= (both inclusive)."""
    date_from, date_to = date_range(params)
    model_field = qs.model._meta.get_field(field.split("__")[0])
    lookup = field if model_field.get_internal_type() == "DateField" else f"{field}__date"
    if date_from:
        qs = qs.filter(**{f"{lookup}__gte": date_from})
    if date_to:
        qs = qs.filter(**{f"{lookup}__lte": date_to})
    return qs


def period_start(period, today=None):
    """First date of 'day', 'week' (Monday) or 'month' containing `today` (company time)."""
    today = today or timezone.localdate()
    if period == "day":
        return today
    if period == "week":
        return today - timedelta(days=today.weekday())
    return today.replace(day=1)


def clean_period(value, default="week"):
    return value if value in dict(PERIODS) else default


def _cell(value):
    # Spreadsheets run cells that start with these characters as formulas (CSV injection).
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return response


def query_string(request):
    """The current GET filters without `page`, for pagination links."""
    params = request.GET.copy()
    params.pop("page", None)
    params.pop("export", None)
    return params.urlencode()


# --- the shared filter bar ---------------------------------------------------------------
# A view describes its filters once; partials/filter_bar.html draws them closed by default,
# with the active ones shown as chips that remove themselves.

class F:
    """One filter field. kind: 'text', 'select' or 'date'. `main` fields show first; the rest sit under
    "More filters". `options` is a list of (value, label) for selects (an "Any" choice is added)."""

    def __init__(self, name, label, kind="text", options=(), hint="", main=False, placeholder="", any_label="Any"):
        self.name, self.label, self.kind, self.hint, self.main = name, label, kind, hint, main
        self.options, self.placeholder, self.any_label = [(str(v), str(lbl)) for v, lbl in options], placeholder, any_label
        self.value = ""

    @property
    def value_label(self):
        if self.kind == "select":
            return dict(self.options).get(self.value, self.value)
        if self.kind == "date":
            date = parse_date(self.value)
            return date.strftime("%d %b %Y") if date else self.value
        return f'"{self.value}"'


def filter_bar(request, fields):
    """Context for partials/filter_bar.html: the fields with their current values, the active
    filters as removable chips, and the other GET values to keep (tabs, scope, show...)."""
    names = {f.name for f in fields}
    active = []
    for f in fields:
        f.value = request.GET.get(f.name, "")
        if f.value:
            params = request.GET.copy()
            params.pop(f.name, None)
            params.pop("page", None)
            active.append({"label": f.label, "value": f.value_label, "remove": "?" + params.urlencode()})
    keep = [(k, v) for k in request.GET for v in request.GET.getlist(k) if k not in names and k not in ("page", "export")]
    return {
        "main": [f for f in fields if f.main] or fields[:2],
        "more": [f for f in fields if not f.main] if any(f.main for f in fields) else fields[2:],
        "active": active,
        "keep": keep,
        "clear": "?" + "&".join(f"{k}={v}" for k, v in keep) if keep else "?",
    }


def month_groups(items, field, totals=None):
    """Split a newest-first list into months for <details class="fold"> sections. Only the current month
    is open (or the newest one, when nothing is from this month). `totals` maps "YYYY-MM" to extra figures."""
    this_month = timezone.localdate().strftime("%Y-%m")
    groups = []
    for item in items:
        value = getattr(item, field)
        if isinstance(value, datetime):
            value = timezone.localtime(value).date()
        key = value.strftime("%Y-%m")
        if not groups or groups[-1]["key"] != key:
            groups.append({"key": key, "label": value.strftime("%B %Y"), "items": [], "open": key == this_month,
                           "totals": (totals or {}).get(key)})
        groups[-1]["items"].append(item)
    if groups and not any(g["open"] for g in groups):
        groups[0]["open"] = True
    return groups
