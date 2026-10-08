"""Shared list helpers: date-range filters, day/week/month periods and safe CSV downloads."""
import csv
from datetime import timedelta

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
