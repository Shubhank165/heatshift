"""Daily-plan workflow steps, orchestrated by Step Functions:
fetch -> risk -> plan -> notify. Steps pass small references, data lives in S3/DynamoDB."""
import json
import os
from datetime import datetime, timedelta

import boto3

from heatshift import heat, planner, store, weather

sns = boto3.client("sns")
TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN", "")
APP_URL = os.environ.get("APP_URL", "")


def _resolve_date(event):
    if event.get("date"):
        return event["date"]
    offset = int(event.get("date_offset", 1))
    return (weather.today_ist() + timedelta(days=offset)).isoformat()


def fetch(event, _ctx):
    fleet_id = event["fleet_id"]
    plan_date = _resolve_date(event)
    zones = store.query(fleet_id, "ZONE#")
    url, raw = weather.fetch_hourly(zones, plan_date)
    run_id = datetime.now(weather.IST).strftime("%Y%m%dT%H%M%S")
    key = store.put_raw(fleet_id, plan_date, run_id, {"source": url, "zones": zones, "data": raw})
    return {"fleet_id": fleet_id, "date": plan_date, "run_id": run_id, "raw_key": key}


def risk(event, _ctx):
    raw = store.get_raw(event["raw_key"])
    hourly = weather.parse(raw["zones"], raw["data"])
    for zone_id, rows in hourly.items():
        store.put(event["fleet_id"], f"RISK#{event['date']}#{zone_id}", {
            "zone": zone_id, "date": event["date"], "run_id": event["run_id"],
            "hours": heat.hourly_risk(rows),
        })
    return event


def plan(event, _ctx):
    fleet_id, plan_date = event["fleet_id"], event["date"]
    fleet = store.load_fleet(fleet_id)
    risk_items = store.query(fleet_id, f"RISK#{plan_date}#")
    zone_risk = {r["zone"]: r["hours"] for r in risk_items}
    result = planner.plan_day(plan_date, fleet["zones"], fleet["workers"], zone_risk,
                              fleet["rest_points"], fleet["meta"].get("policy"))
    previous = store.get(fleet_id, f"PLAN#{plan_date}")
    result.update({"run_id": event["run_id"], "status": "PROPOSED",
                   "generated_at": datetime.now(weather.IST).isoformat(timespec="minutes")})
    store.put(fleet_id, f"PLAN#{plan_date}", result)
    prev_peak = previous["kpis"]["peak_band"] if previous else None
    escalated = bool(prev_peak) and heat.BAND_ORDER[result["kpis"]["peak_band"]] > heat.BAND_ORDER[prev_peak]
    return {**event, "kpis": result["kpis"], "escalated": escalated, "previous_peak": prev_peak,
            "top_actions": [a["title"] for a in result["actions"][:6]]}


def notify(event, _ctx):
    if not TOPIC_ARN:
        return {**event, "notified": False}
    k = event["kpis"]
    prefix = "⚠ ESCALATED: " if event.get("escalated") else ""
    subject = f"{prefix}HeatShift plan for {event['date']}: {k['peak_band']}"[:100]
    lines = [
        f"HeatShift daily brief — {event['date']}",
        "",
        f"Peak heat stress: {k['peak_band']} (WBGT {k['peak_wbgt']}°C)",
        f"No outdoor work: {k['stop_window'] or 'none needed'}",
        f"Workers rostered: {k['workers']} · shifts restructured: {k['shifts_changed']} · new joiners: {k['new_joiners']}",
        f"Worker-hours in DANGER or worse: {k['risk_hours_original']} → {k['risk_hours_planned']} after plan",
        f"Capacity change: {k['capacity_change_pct']}% · cost of protection: ₹{k['cost_of_protection_inr']:,}",
        "",
        "Recommended actions:",
        *[f"  • {t}" for t in event.get("top_actions", [])],
        "",
        f"Review and approve: {APP_URL}" if APP_URL else "",
    ]
    if event.get("escalated"):
        lines.insert(1, f"Forecast worsened since the last plan ({event['previous_peak']} → {k['peak_band']}).")
    sns.publish(TopicArn=TOPIC_ARN, Subject=subject, Message="\n".join(lines))
    return {**event, "notified": True}


def failure(event, _ctx):
    """Called by the workflow's Catch: tell the manager the plan is stale."""
    if TOPIC_ARN:
        sns.publish(TopicArn=TOPIC_ARN, Subject="HeatShift: daily plan FAILED",
                    Message="Today's plan could not be generated; the last good plan is still shown.\n\n"
                            + json.dumps(event, default=str)[:3000])
    return event
