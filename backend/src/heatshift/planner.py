"""Shift planner: turns zone risk + roster + policy into a day plan.

Design principles (see README "Incentives"):
- Moving the work, not the risk: hours in the stop band are removed for everyone
  in the zone; shifts are restructured into cooler hours.
- Income protection: scheduled breaks are paid and planned hours are guaranteed.
  There is deliberately no "heat surge pay" option.
"""
import math
from datetime import date

from .heat import BAND_ORDER, REST_MIN, band_for

DEFAULT_POLICY = {
    "stop_band": "EXTREME",
    "acclimatization_days": 14,
    "acclimatization_offset_c": 2.5,
    "op_start": 6,
    "op_end": 22,
    "hourly_rate_inr": 120,
    "paid_breaks": True,
    "guarantee_planned_hours": True,
    "heat_surge_pay": False,  # locked off by design
    "max_rest_km": 2.0,
    "deliveries_per_hour": 3,
}

WATER_L_PER_HOUR = {"SAFE": 0.5, "CAUTION": 0.75, "DANGER": 1.0, "SEVERE": 1.0, "EXTREME": 1.0}


def haversine_km(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _blocks(hours):
    """[6,7,8,15,16] -> [(6,9),(15,17)] as [start, end) pairs."""
    out = []
    for h in sorted(hours):
        if out and out[-1][1] == h:
            out[-1][1] = h + 1
        else:
            out.append([h, h + 1])
    return [tuple(b) for b in out]


def _fmt_blocks(blocks):
    return ", ".join(f"{s:02d}:00–{e:02d}:00" for s, e in blocks) or "No shift"


def _is_new(worker, plan_date, policy):
    joined = date.fromisoformat(worker["join_date"])
    days = (date.fromisoformat(plan_date) - joined).days
    return 0 <= days < policy["acclimatization_days"]


def _breaks(hour, band):
    rest = REST_MIN[band]
    if rest == 0:
        return []
    start = 60 - rest
    return [f"{hour:02d}:{start:02d}–{hour + 1:02d}:00"]


def nearest_rest(zone, rest_points):
    best = None
    for rp in rest_points:
        if not rp.get("designated"):
            continue
        d = haversine_km(zone["lat"], zone["lon"], rp["lat"], rp["lon"])
        if best is None or d < best[0]:
            best = (d, rp)
    if not best:
        return None
    return {**best[1], "distance_km": round(best[0], 2)}


def best_candidate(zone, rest_points):
    best = None
    for rp in rest_points:
        if rp.get("designated"):
            continue
        d = haversine_km(zone["lat"], zone["lon"], rp["lat"], rp["lon"])
        if best is None or d < best[0]:
            best = (d, rp)
    return {**best[1], "distance_km": round(best[0], 2)} if best else None


def plan_day(plan_date, zones, workers, zone_risk, rest_points, policy=None):
    """zone_risk: {zone_id: [{hour, wbgt, band, ...}, ...]} for hours 0..23."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    stop_rank = BAND_ORDER[policy["stop_band"]]
    rate = policy["hourly_rate_inr"]
    op_hours = list(range(policy["op_start"], policy["op_end"]))
    zones_by_id = {z["id"]: z for z in zones}

    zone_summaries = {}
    for z in zones:
        rows = {r["hour"]: r for r in zone_risk.get(z["id"], [])}
        stop = [h for h in op_hours if h in rows and BAND_ORDER[rows[h]["band"]] >= stop_rank]
        peak = max(rows.values(), key=lambda r: r["wbgt"]) if rows else None
        rest = nearest_rest(z, rest_points)
        zone_summaries[z["id"]] = {
            "id": z["id"],
            "name": z["name"],
            "lat": z["lat"],
            "lon": z["lon"],
            "peak_band": peak["band"] if peak else "SAFE",
            "peak_wbgt": peak["wbgt"] if peak else None,
            "peak_hour": peak["hour"] if peak else None,
            "stop_window": _fmt_blocks(_blocks(stop)) if stop else None,
            "stop_hours": stop,
            "nearest_rest": rest,
            "coverage_gap": rest is None or rest["distance_km"] > policy["max_rest_km"],
            "workers": 0,
            "shifts_changed": 0,
        }

    cards = []
    totals = {
        "workers": 0, "new_joiners": 0, "shifts_changed": 0,
        "hours_planned": 0.0, "hours_effective": 0.0, "hours_lost": 0.0,
        "risk_hours_original": 0, "risk_hours_planned": 0,
        "water_l": 0.0, "ors": 0, "peak_hours_moved": 0,
    }

    for w in workers:
        z = zones_by_id.get(w["zone"])
        if not z:
            continue
        rows = {r["hour"]: r for r in zone_risk.get(z["id"], [])}
        new = _is_new(w, plan_date, policy)
        offset = policy["acclimatization_offset_c"] if new else 0.0

        def band_at(h):
            r = rows.get(h)
            return band_for(r["wbgt"], offset) if r else "SAFE"

        orig = list(range(w["shift_start"], w["shift_end"]))
        need = len(orig)
        stop = {h for h in op_hours if BAND_ORDER[band_at(h)] >= stop_rank}
        risky = lambda h: BAND_ORDER[band_at(h)] >= BAND_ORDER["DANGER"]
        totals["risk_hours_original"] += sum(1 for h in orig if risky(h))

        if stop & set(orig):
            avail = [h for h in op_hours if h not in stop]
            # prefer hours needing the least rest, then closest to the original shift
            def score(h):
                dist = 0 if w["shift_start"] <= h < w["shift_end"] else min(
                    abs(h - w["shift_start"]), abs(h - (w["shift_end"] - 1)))
                return (REST_MIN[band_at(h)], dist, rows.get(h, {}).get("wbgt", 0))
            new_hours = sorted(sorted(avail, key=score)[:need])
            changed = True
            totals["peak_hours_moved"] += len(stop & set(orig))
        else:
            new_hours = orig
            changed = False

        breaks, eff, water, danger_hours = [], 0.0, 0.0, 0
        for h in new_hours:
            b = band_at(h)
            breaks += _breaks(h, b)
            eff += (60 - REST_MIN[b]) / 60
            water += WATER_L_PER_HOUR[b]
            if risky(h):
                danger_hours += 1
        lost = need - len(new_hours)
        rest = zone_summaries[z["id"]]["nearest_rest"]
        peak_band = max((band_at(h) for h in new_hours), key=lambda b: BAND_ORDER[b], default="SAFE")
        own_stop = sorted(stop)

        cards.append({
            "worker_id": w["id"],
            "name": w["name"],
            "zone": z["id"],
            "zone_name": z["name"],
            "type": w.get("type", "employee"),
            "new_joiner": new,
            "original_shift": _fmt_blocks(_blocks(orig)),
            "shift": _fmt_blocks(_blocks(new_hours)),
            "shift_hours": new_hours,
            "changed": changed,
            "breaks": breaks,
            "stop_window": _fmt_blocks(_blocks(own_stop)) if own_stop else None,
            "peak_band": peak_band,
            "water_l": round(water, 1),
            "nearest_rest": rest,
            "guaranteed_pay_inr": need * rate if policy["guarantee_planned_hours"] else round(eff * rate),
            "hours_lost": lost,
        })

        zs = zone_summaries[z["id"]]
        zs["workers"] += 1
        zs["shifts_changed"] += int(changed)
        totals["workers"] += 1
        totals["new_joiners"] += int(new)
        totals["shifts_changed"] += int(changed)
        totals["hours_planned"] += need
        totals["hours_effective"] += eff
        totals["hours_lost"] += lost
        totals["risk_hours_planned"] += danger_hours
        totals["water_l"] += water
        totals["ors"] += math.ceil(danger_hours / 2)

    # Cost of protection: paid non-productive time (breaks + guaranteed lost hours)
    protected_hours = totals["hours_planned"] - totals["hours_effective"]
    cost = round(protected_hours * rate) if policy["paid_breaks"] else round(totals["hours_lost"] * rate)
    capacity_change = (totals["hours_effective"] / totals["hours_planned"] - 1) if totals["hours_planned"] else 0
    deliveries_to_reslot = totals["peak_hours_moved"] * policy["deliveries_per_hour"]

    peak_zone = max(zone_summaries.values(), key=lambda z: z["peak_wbgt"] or 0, default=None)
    all_stop = sorted({h for z in zone_summaries.values() for h in z["stop_hours"]})

    actions = []
    for zs in sorted(zone_summaries.values(), key=lambda z: -(z["peak_wbgt"] or 0)):
        if zs["stop_window"]:
            actions.append({
                "kind": "stop_window",
                "zone": zs["id"],
                "title": f"{zs['name']}: no outdoor work {zs['stop_window']} ({zs['peak_band']}, WBGT {zs['peak_wbgt']}°C)",
                "detail": f"{zs['shifts_changed']} of {zs['workers']} shifts restructured into cooler hours; "
                          f"everyone in the zone gets the break schedule. Dispatch is blocked in this window.",
            })
    if totals["new_joiners"]:
        actions.append({
            "kind": "acclimatization",
            "title": f"{totals['new_joiners']} new joiners (< {policy['acclimatization_days']} days): stricter limits applied",
            "detail": f"Thresholds lowered by {policy['acclimatization_offset_c']}°C WBGT. Most heat deaths happen in a worker's first days.",
        })
    for zs in zone_summaries.values():
        if zs["coverage_gap"]:
            cand = best_candidate(zs, rest_points)
            near = zs["nearest_rest"]
            actions.append({
                "kind": "coverage_gap",
                "zone": zs["id"],
                "title": f"{zs['name']}: nearest cool point is "
                         + (f"{near['distance_km']} km away" if near else "not set"),
                "detail": (f"Suggested rest point: {cand['name']} ({cand['distance_km']} km from zone centre)."
                           if cand else "No candidate sites found nearby."),
                "candidate": cand,
            })
    if deliveries_to_reslot:
        actions.append({
            "kind": "reslot",
            "title": f"Move ~{deliveries_to_reslot} delivery slots out of {_fmt_blocks(_blocks(all_stop))}",
            "detail": "Offer customers morning/evening slots instead.",
            "customer_message": "Your delivery has moved to a cooler time slot to keep our delivery partner "
                                "safe in today's extreme heat. Thank you for understanding.",
        })
    actions.append({
        "kind": "supplies",
        "title": f"Stock {round(totals['water_l'])} L drinking water and {totals['ors']} ORS sachets at the hub",
        "detail": "Estimated from planned hours in each heat band.",
    })

    return {
        "date": plan_date,
        "policy": policy,
        "kpis": {
            "workers": totals["workers"],
            "peak_band": peak_zone["peak_band"] if peak_zone else "SAFE",
            "peak_wbgt": peak_zone["peak_wbgt"] if peak_zone else None,
            "stop_window": _fmt_blocks(_blocks(all_stop)) if all_stop else None,
            "risk_hours_original": totals["risk_hours_original"],
            "risk_hours_planned": totals["risk_hours_planned"],
            "shifts_changed": totals["shifts_changed"],
            "new_joiners": totals["new_joiners"],
            "capacity_change_pct": round(capacity_change * 100, 1),
            "hours_lost": totals["hours_lost"],
            "cost_of_protection_inr": cost,
            "water_l": round(totals["water_l"]),
            "ors": totals["ors"],
        },
        "zones": list(zone_summaries.values()),
        "actions": actions,
        "cards": cards,
    }
