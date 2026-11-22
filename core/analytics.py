"""Numbers behind the Analytics page (Enterprise: advanced analytics). Built on build_report so
every figure agrees with the Reports page."""
from collections import defaultdict
from datetime import datetime, timedelta

from django.utils import timezone

from .services import build_report

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
BUCKET_MIN = 15


def _rate(attended, expected):
    return round(attended * 100 / expected, 1) if expected else None


def _avg_minutes(times):
    return sum(t.hour * 60 + t.minute for t in times) / len(times) if times else None


def _clock(minutes):
    if minutes is None:
        return "—"
    m = int(round(minutes))
    return f"{datetime(2000, 1, 1, (m // 60) % 24, m % 60):%I:%M %p}".lstrip("0")


def summarise(org, start, end, members):
    """KPIs, day/week trend, weekday pattern, arrival histogram, group comparison and people lists."""
    members = list(members)
    report = build_report(org, start, end, members=members)
    rows, days = report["rows"], report["days"]

    # Per-day tallies from the register codes (P on time, L late, E leave, A absent)
    per_day = {d: defaultdict(int) for d in days}
    for r in rows:
        for d, code in zip(days, r["cells"]):
            if code in "PLEA" and code:
                per_day[d][code] += 1

    attended = sum(r["attended"] for r in rows)
    expected = sum(r["expected"] for r in rows)
    late = sum(r["late"] for r in rows)
    arrivals = [timezone.localtime(rec.check_in).time() for r in rows for rec in r["records"].values() if rec.check_in]
    worked = [rec.worked_hours for r in rows for rec in r["records"].values() if rec.worked_hours]
    kpis = {
        "rate": _rate(attended, expected),
        "punctuality": _rate(attended - late, attended),
        "arrival_min": _avg_minutes(arrivals),
        "hours": round(sum(worked) / len(worked), 1) if worked else None,
        "absent": sum(r["absent"] for r in rows),
        "late": late,
    }
    kpis["arrival"] = _clock(kpis["arrival_min"])

    # Trend: daily for up to five weeks, weekly beyond that
    counted = [d for d in days if sum(per_day[d][c] for c in "PLA")]
    if (end - start).days <= 35:
        trend = [{"label": f"{d:%d %b}", "rate": _rate(per_day[d]["P"] + per_day[d]["L"],
                                                        per_day[d]["P"] + per_day[d]["L"] + per_day[d]["A"])}
                 for d in counted]
        trend_unit = "day"
    else:
        weeks = defaultdict(lambda: [0, 0])
        for d in counted:
            wk = d - timedelta(days=d.weekday())
            weeks[wk][0] += per_day[d]["P"] + per_day[d]["L"]
            weeks[wk][1] += per_day[d]["P"] + per_day[d]["L"] + per_day[d]["A"]
        trend = [{"label": f"w/c {wk:%d %b}", "rate": _rate(a, e)} for wk, (a, e) in sorted(weeks.items())]
        trend_unit = "week"

    # Weekday pattern: share of expected (non-leave) days that were on time / late / absent
    wd = {i: defaultdict(int) for i in range(7)}
    for d in counted:
        for c in "PLA":
            wd[d.weekday()][c] += per_day[d][c]
    weekdays = []
    for i in org.working_day_list():
        t = sum(wd[i].values())
        if t:
            weekdays.append({"label": WEEKDAYS[i], "n": t,
                             "on_time": round(wd[i]["P"] * 100 / t, 1), "late": round(wd[i]["L"] * 100 / t, 1),
                             "absent": round(wd[i]["A"] * 100 / t, 1)})

    # Arrival histogram: 15-minute buckets from an hour before start to two hours after
    start_min = org.work_start.hour * 60 + org.work_start.minute
    cutoff_min = start_min + org.grace_minutes
    lo, hi = start_min - 60, start_min + 120
    buckets = [{"from": m, "n": 0} for m in range(lo, hi, BUCKET_MIN)]
    early = later = 0
    for t in arrivals:
        m = t.hour * 60 + t.minute
        if m < lo:
            early += 1
        elif m >= hi:
            later += 1
        else:
            buckets[(m - lo) // BUCKET_MIN]["n"] += 1
    for b in buckets:
        b["label"] = f"{_clock(b['from'])}–{_clock(b['from'] + BUCKET_MIN)}"
        b["late"] = b["from"] + BUCKET_MIN > cutoff_min
    histogram = {"buckets": buckets, "early": early, "later": later, "start": _clock(start_min),
                 "cutoff": _clock(cutoff_min)}

    # Group comparison (departments, branches)
    def groups(key, name_of):
        out = defaultdict(lambda: {"people": 0, "attended": 0, "expected": 0, "late": 0, "hours": 0.0})
        for r in rows:
            g = out[key(r["user"])]
            g["people"] += 1
            g["attended"] += r["attended"]
            g["expected"] += r["expected"]
            g["late"] += r["late"]
            g["hours"] += r["hours"]
        result = []
        for k, g in out.items():
            result.append({"name": name_of(k), "people": g["people"], "rate": _rate(g["attended"], g["expected"]) or 0,
                           "late_rate": _rate(g["late"], g["attended"]) or 0,
                           "hours": round(g["hours"] / g["people"], 1) if g["people"] else 0})
        return sorted(result, key=lambda x: -x["rate"])

    dept_names = {r["user"].department_id: r["user"].department.name for r in rows if r["user"].department_id}
    branch_names = {r["user"].branch_id: r["user"].branch.name for r in rows if r["user"].branch_id}
    depts = groups(lambda u: u.department_id, lambda k: dept_names.get(k, "No department"))
    branches = groups(lambda u: u.branch_id, lambda k: branch_names.get(k, "Main location"))

    with_days = [r for r in rows if r["expected"]]
    people = {
        "most_late": sorted([r for r in with_days if r["late"]], key=lambda r: (-r["late"], r["rate"]))[:5],
        "most_absent": sorted([r for r in with_days if r["absent"]], key=lambda r: (-r["absent"], r["rate"]))[:5],
        "perfect": sorted([r for r in with_days if r["attended"] == r["expected"] and not r["late"]
                           and r["expected"] >= 3], key=lambda r: r["user"].display_name)[:10],
    }
    return {"kpis": kpis, "trend": trend, "trend_unit": trend_unit, "weekdays": weekdays, "histogram": histogram,
            "departments": depts, "branches": branches, "people": people, "report": report}


def deltas(now, before):
    """Change in each KPI versus the previous period (None when either side is missing)."""
    out = {}
    for k in ("rate", "punctuality", "hours", "absent", "late", "arrival_min"):
        a, b = now["kpis"].get(k), before["kpis"].get(k)
        out[k] = None if a is None or b is None else round(a - b, 1)
    return out
