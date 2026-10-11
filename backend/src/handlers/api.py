"""HTTP API for the dashboard, worker cards and dispatch systems."""
import json
import os
import re
from datetime import datetime

import boto3

from heatshift import heat, notify, onboarding, store, weather
from heatshift.planner import DEFAULT_POLICY

sns = boto3.client("sns")
sfn = boto3.client("stepfunctions")
TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN", "")
APP_URL = os.environ.get("APP_URL", "")
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
    p["outbox"] = store.get(fid, f"OUTBOX#{d}")
    return 200, p


def approve_plan(fid, d, body, **_):
    p = store.get(fid, f"PLAN#{d}")
    if not p:
        return 404, {"error": "no plan for this date"}
    p.update(status="APPROVED", approved_at=_now(), approved_by=body.get("by", "manager"))
    store.put(fid, f"PLAN#{d}", p)
    # Approval is what releases the plan to workers: build their messages.
    outbox = notify.build_outbox(p, store.query(fid, "WORKER#"), APP_URL)
    outbox["created_at"] = _now()
    store.put(fid, f"OUTBOX#{d}", outbox)
    if TOPIC_ARN:
        chans = ", ".join(f"{n} {c}" for c, n in sorted(outbox["by_channel"].items(), key=lambda x: -x[1]))
        sns.publish(TopicArn=TOPIC_ARN, Subject=f"HeatShift: plan for {d} approved, {len(outbox['messages'])} workers notified",
                    Message=f"The heat plan for {d} was approved at {p['approved_at']}.\n"
                            f"{len(outbox['messages'])} worker messages queued: {chans}.\n{APP_URL}")
    return 200, {"status": "APPROVED", "approved_at": p["approved_at"], "messages": len(outbox["messages"])}


def import_roster(fid, body, **_):
    """POST {"csv": "...", "dry_run": true|false}. Upserts workers; the raw file is archived in S3."""
    text = body.get("csv") or ""
    if not text.strip():
        return 400, {"error": "csv is empty"}
    zones = store.query(fid, "ZONE#")
    workers, errors = onboarding.parse_roster(text, zones)
    existing = {w["id"] for w in store.query(fid, "WORKER#")}
    report = {"valid": len(workers), "errors": errors,
              "new": sum(w["id"] not in existing for w in workers),
              "updated": sum(w["id"] in existing for w in workers),
              "preview": workers[:50], "dry_run": bool(body.get("dry_run"))}
    if body.get("dry_run") or not workers:
        return 200, report
    key = store.put_upload(fid, "roster", text)
    with store.TABLE.batch_writer() as batch:
        for w in workers:
            batch.put_item(Item=store._to_ddb({**w, "pk": store.pk(fid), "sk": f"WORKER#{w['id']}"}))
    return 200, {**report, "imported": len(workers), "archived_to": f"s3://{store.BUCKET}/{key}"}


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
    return 202, {"execution_arn": ex["executionArn"], "run": ex["executionArn"].rsplit(":", 1)[1]}


STEPS = [("FetchForecast", "Fetch hourly forecast for every zone"),
         ("ComputeHeatRisk", "Compute WBGT and risk band per zone-hour"),
         ("PlanShifts", "Re-plan shifts, breaks and rest points"),
         ("NotifyManager", "Send the manager brief")]


def run_status(fid, run, **_):
    """Live progress of a planning run, read from the Step Functions execution history."""
    arn = STATE_MACHINE_ARN.replace(":stateMachine:", ":execution:") + ":" + run
    ex = sfn.describe_execution(executionArn=arn)
    state = {name: "pending" for name, _ in STEPS}
    for e in sfn.get_paginator("get_execution_history").paginate(executionArn=arn).build_full_result()["events"]:
        if e["type"] == "TaskStateEntered":
            state[e["stateEnteredEventDetails"]["name"]] = "running"
        elif e["type"] == "TaskStateExited":
            state[e["stateExitedEventDetails"]["name"]] = "done"
        elif e["type"] in ("LambdaFunctionFailed", "TaskFailed", "LambdaFunctionTimedOut"):
            for name in state:
                if state[name] == "running":
                    state[name] = "retrying"
    status = ex["status"]
    if status == "FAILED":
        for name in state:
            if state[name] in ("running", "retrying"):
                state[name] = "failed"
    out = json.loads(ex.get("output") or "{}") if status == "SUCCEEDED" else {}
    if "PlanFailed" in state:
        state.pop("PlanFailed")
    return 200, {"status": status, "date": out.get("date") or json.loads(ex["input"]).get("date"),
                 "steps": [{"id": n, "label": l, "state": state[n]} for n, l in STEPS],
                 "started_at": ex["startDate"].isoformat(), "kpis": out.get("kpis")}


ROUTES = [
    ("GET", r"^/fleets/(?P<fid>[\w-]+)$", get_fleet),
    ("GET", r"^/fleets/(?P<fid>[\w-]+)/plans/(?P<d>\d{4}-\d{2}-\d{2})$", get_plan),
    ("POST", r"^/fleets/(?P<fid>[\w-]+)/plans/(?P<d>\d{4}-\d{2}-\d{2})/approve$", approve_plan),
    ("POST", r"^/fleets/(?P<fid>[\w-]+)/plans$", run_plan),
    ("POST", r"^/fleets/(?P<fid>[\w-]+)/roster$", import_roster),
    ("GET", r"^/fleets/(?P<fid>[\w-]+)/runs/(?P<run>[\w-]+)$", run_status),
    ("GET", r"^/fleets/(?P<fid>[\w-]+)/workers/(?P<wid>\w+)/card$", worker_card),
    ("GET", r"^/fleets/(?P<fid>[\w-]+)/dispatch-check$", dispatch_check),
    ("POST", r"^/fleets/(?P<fid>[\w-]+)/overrides$", create_override),
    ("POST", r"^/fleets/(?P<fid>[\w-]+)/checkins$", create_checkin),
    ("PUT", r"^/fleets/(?P<fid>[\w-]+)/policy$", update_policy),
]


def handler(event, _ctx):
    method = event["requestContext"]["http"]["method"]
    if method == "OPTIONS":  # CORS preflight: the ANY proxy route forwards it here
        return {"statusCode": 204, "headers": {}, "body": ""}
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
