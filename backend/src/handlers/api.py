"""HTTP API for the dashboard, worker cards and dispatch systems."""
import json
import os
import re
from datetime import datetime

import boto3

from heatshift import heat, store, weather
from heatshift.planner import DEFAULT_POLICY

sns = boto3.client("sns")
sfn = boto3.client("stepfunctions")
TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN", "")
STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")
LOCKED_POLICY = {"heat_surge_pay": False}  # never configurable, by design


def _resp(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(body, default=str, ensure_ascii=False)}


def _now():
    return datetime.now(weather.IST).isoformat(timespec="seconds")


def get_fleet(fid, **_):
    f = store.load_fleet(fid)
    f["meta"]["policy"] = {**DEFAULT_POLICY, **f["meta"].get("policy", {})}
    f["plans"] = sorted(
        ({"date": p["date"], "status": p.get("status"), "peak_band": p["kpis"]["peak_band"]}
         for p in store.query(fid, "PLAN#")), key=lambda p: p["date"])
    return 200, f


def get_plan(fid, d, **_):
    p = store.get(fid, f"PLAN#{d}")
    if not p:
        return 404, {"error": "no plan for this date"}
    p["risk"] = {r["zone"]: r["hours"] for r in store.query(fid, f"RISK#{d}#")}
    p["overrides"] = store.query(fid, f"OVERRIDE#{d}")
    p["checkins"] = store.query(fid, f"CHECKIN#{d}")
    return 200, p


def approve_plan(fid, d, body, **_):
    p = store.get(fid, f"PLAN#{d}")
    if not p:
        return 404, {"error": "no plan for this date"}
    p.update(status="APPROVED", approved_at=_now(), approved_by=body.get("by", "manager"))
    store.put(fid, f"PLAN#{d}", p)
    return 200, {"status": "APPROVED", "approved_at": p["approved_at"]}


def worker_card(fid, wid, query, **_):
    d = query.get("date") or weather.today_ist().isoformat()
    p = store.get(fid, f"PLAN#{d}")
    if not p:
        return 404, {"error": "no plan for this date"}
    card = next((c for c in p["cards"] if c["worker_id"] == wid), None)
    if not card:
        return 404, {"error": "worker not on this plan"}
    return 200, {**card, "date": d, "plan_status": p.get("status")}


def dispatch_check(fid, query, **_):
    """Called by a dispatch system before assigning a job.
    GET ?zone=Z1&at=2026-05-28T13:30[&worker=W001]"""
    zone, at = query.get("zone"), query.get("at")
    if not zone or not at:
        return 400, {"error": "zone and at are required"}
    d, hour = at[:10], int(at[11:13])
    r = store.get(fid, f"RISK#{d}#{zone}")
    if not r:
        return 404, {"error": "no risk data for this zone/date"}
    row = next((h for h in r["hours"] if h["hour"] == hour), None)
    policy = {**DEFAULT_POLICY, **store.get(fid, "META").get("policy", {})}
    band = row["band"] if row else "SAFE"
    reason = None
    if query.get("worker"):
        p = store.get(fid, f"PLAN#{d}")
        card = next((c for c in (p or {}).get("cards", []) if c["worker_id"] == query["worker"]), None)
        if card and card["new_joiner"] and row:
            band = heat.band_for(row["wbgt"], policy["acclimatization_offset_c"])
        if card and hour not in card["shift_hours"]:
            reason = "Outside this worker's heat-safe shift"
    if heat.BAND_ORDER[band] >= heat.BAND_ORDER[policy["stop_band"]]:
        reason = f"{band} heat stress (WBGT {row['wbgt']}°C): no outdoor work in this window"
    return 200, {"allowed": reason is None, "band": band, "wbgt": row["wbgt"] if row else None,
                 "reason": reason, "override": "POST /fleets/{id}/overrides with a reason (logged)"}


def create_override(fid, body, **_):
    for f in ("zone", "at", "reason"):
        if not body.get(f):
            return 400, {"error": f"{f} is required"}
    item = {"zone": body["zone"], "at": body["at"], "reason": body["reason"],
            "job": body.get("job"), "by": body.get("by", "manager"), "created_at": _now()}
    store.put(fid, f"OVERRIDE#{body['at'][:10]}#{_now()}", item)
    return 201, item


def create_checkin(fid, body, **_):
    wid, status = body.get("worker_id"), body.get("status")
    if status not in ("ok", "unwell") or not wid:
        return 400, {"error": "worker_id and status ok|unwell required"}
    d = body.get("date") or weather.today_ist().isoformat()
    item = {"worker_id": wid, "status": status, "date": d, "created_at": _now(),
            "name": body.get("name"), "zone": body.get("zone")}
    store.put(fid, f"CHECKIN#{d}#{_now()}#{wid}", item)
    if status == "unwell" and TOPIC_ARN:
        sns.publish(TopicArn=TOPIC_ARN, Subject=f"🆘 HeatShift: {body.get('name') or wid} reports feeling unwell",
                    Message=f"{body.get('name') or wid} (zone {body.get('zone')}) tapped 'I feel unwell' at "
                            f"{item['created_at']}.\nCall them now and direct them to the nearest cool point. "
                            f"This report never affects their pay or rating.")
    return 201, item


def update_policy(fid, body, **_):
    meta = store.get(fid, "META")
    allowed = {k: body[k] for k in DEFAULT_POLICY if k in body}
    meta["policy"] = {**DEFAULT_POLICY, **meta.get("policy", {}), **allowed, **LOCKED_POLICY}
    store.put(fid, "META", meta)
    return 200, meta["policy"]


def run_plan(fid, body, **_):
    payload = {"fleet_id": fid}
    if body.get("date"):
        payload["date"] = body["date"]
    ex = sfn.start_execution(stateMachineArn=STATE_MACHINE_ARN, input=json.dumps(payload))
    return 202, {"execution_arn": ex["executionArn"]}


ROUTES = [
    ("GET", r"^/fleets/(?P<fid>[\w-]+)$", get_fleet),
    ("GET", r"^/fleets/(?P<fid>[\w-]+)/plans/(?P<d>\d{4}-\d{2}-\d{2})$", get_plan),
    ("POST", r"^/fleets/(?P<fid>[\w-]+)/plans/(?P<d>\d{4}-\d{2}-\d{2})/approve$", approve_plan),
    ("POST", r"^/fleets/(?P<fid>[\w-]+)/plans$", run_plan),
    ("GET", r"^/fleets/(?P<fid>[\w-]+)/workers/(?P<wid>\w+)/card$", worker_card),
    ("GET", r"^/fleets/(?P<fid>[\w-]+)/dispatch-check$", dispatch_check),
    ("POST", r"^/fleets/(?P<fid>[\w-]+)/overrides$", create_override),
    ("POST", r"^/fleets/(?P<fid>[\w-]+)/checkins$", create_checkin),
    ("PUT", r"^/fleets/(?P<fid>[\w-]+)/policy$", update_policy),
]


def handler(event, _ctx):
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"].rstrip("/") or "/"
    body = json.loads(event.get("body") or "{}") if method in ("POST", "PUT") else {}
    query = event.get("queryStringParameters") or {}
    for m, pattern, fn in ROUTES:
        match = re.match(pattern, path)
        if match and m == method:
            try:
                status, out = fn(**match.groupdict(), body=body, query=query)
            except KeyError as e:
                status, out = 404, {"error": str(e)}
            return _resp(status, out)
    return _resp(404, {"error": f"no route for {method} {path}"})
