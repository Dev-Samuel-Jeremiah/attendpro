from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from billing import catalog
from billing.services import feature_required

from . import analytics
from .decorators import org_admin_required
from .views import _branch_filter, _parse_date

PRESETS = [("7", "Last 7 days"), ("30", "Last 30 days"), ("90", "Last 90 days"), ("month", "This month"),
           ("last_month", "Last month")]


def _period(request, today):
    preset = request.GET.get("range", "30")
    if request.GET.get("start") or request.GET.get("end"):
        start = _parse_date(request.GET.get("start"), today - timedelta(days=29))
        end = min(_parse_date(request.GET.get("end"), today), today)
        preset = "custom"
    elif preset == "month":
        start, end = today.replace(day=1), today
    elif preset == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    else:
        n = int(preset) if preset in ("7", "30", "90") else 30
        preset = str(n)
        start, end = today - timedelta(days=n - 1), today
    if end < start:
        start, end = end, start
    start = max(start, end - timedelta(days=366))
    return preset, start, end


def _tiles(k, d):
    def tile(label, value, delta, unit, up_is_good, sub=""):
        if delta is None or delta == 0:
            change, tone, arrow = ("No change" if delta == 0 else "No earlier data"), "flat", ""
        else:
            change = f"{'+' if delta > 0 else '−'}{abs(delta):g}{unit}"
            arrow = "▲" if delta > 0 else "▼"            # direction of the change
            tone = "good" if (delta > 0) == up_is_good else "bad"   # colour: better or worse
        return {"label": label, "value": value, "change": change, "tone": tone, "arrow": arrow, "sub": sub}

    return [
        tile("Attendance rate", f"{k['rate']:g}%" if k["rate"] is not None else "—", d["rate"], " pts", True),
        tile("On time", f"{k['punctuality']:g}%" if k["punctuality"] is not None else "—", d["punctuality"], " pts",
             True, "of arrivals"),
        tile("Average arrival", k["arrival"], round(d["arrival_min"]) if d["arrival_min"] is not None else None,
             " min", False),
        tile("Average day", f"{k['hours']:g} h" if k["hours"] is not None else "—", d["hours"], " h", True,
             "on site"),
        tile("Absences", f"{k['absent']:,}", d["absent"], "", False, f"{k['late']:,} late arrivals"),
    ]


@org_admin_required
@feature_required(catalog.ANALYTICS)
def analytics_page(request):
    org = request.user.organisation
    today = timezone.localdate()
    preset, start, end = _period(request, today)
    dept = request.GET.get("dept", "")
    members = org.members.filter(is_active=True).select_related("department", "branch")
    if dept:
        members = members.filter(department_id=dept)
    members, branch, branches = _branch_filter(request, org, members)

    now = analytics.summarise(org, start, end, members)
    length = (end - start).days + 1
    before = analytics.summarise(org, start - timedelta(days=length), start - timedelta(days=1), members)
    chart_data = {"trend": now["trend"], "trend_unit": now["trend_unit"], "weekdays": now["weekdays"],
                  "histogram": now["histogram"]}
    return render(request, "manage/analytics.html", {
        "a": now, "tiles": _tiles(now["kpis"], analytics.deltas(now, before)), "chart_data": chart_data,
        "length": length,
        "preset": preset, "presets": PRESETS, "start": start, "end": end, "dept": dept,
        "departments": org.departments.all(), "branch": branch, "branches": branches,
        "show_branches": branches is not None and len(now["branches"]) > 1,
    })
