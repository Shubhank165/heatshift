"""Persistence: one DynamoDB table (pk/sk) and an S3 data lake for raw forecasts."""
import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

_ddb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")
TABLE = _ddb.Table(os.environ.get("TABLE_NAME", "HeatShift"))
BUCKET = os.environ.get("DATA_BUCKET", "")


def _to_ddb(obj):
    return json.loads(json.dumps(obj), parse_float=Decimal)


def _from_ddb(obj):
    if isinstance(obj, list):
        return [_from_ddb(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def pk(fleet_id):
    return f"FLEET#{fleet_id}"


def put(fleet_id, sk, item):
    TABLE.put_item(Item=_to_ddb({**item, "pk": pk(fleet_id), "sk": sk}))


def get(fleet_id, sk):
    item = TABLE.get_item(Key={"pk": pk(fleet_id), "sk": sk}).get("Item")
    return _clean(_from_ddb(item)) if item else None


def query(fleet_id, prefix):
    items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(pk(fleet_id)) & Key("sk").begins_with(prefix)}
    while True:
        resp = TABLE.query(**kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [_clean(_from_ddb(i)) for i in items]


def _clean(item):
    return {k: v for k, v in item.items() if k not in ("pk", "sk")}


def load_fleet(fleet_id):
    meta = get(fleet_id, "META")
    if not meta:
        raise KeyError(f"unknown fleet {fleet_id}")
    return {
        "meta": meta,
        "zones": query(fleet_id, "ZONE#"),
        "workers": query(fleet_id, "WORKER#"),
        "rest_points": query(fleet_id, "REST#"),
    }


def put_raw(fleet_id, plan_date, run_id, payload):
    key = f"raw/fleet={fleet_id}/date={plan_date}/{run_id}.json"
    _s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(payload).encode(), ContentType="application/json")
    return key


def get_raw(key):
    return json.loads(_s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())


def put_upload(fleet_id, kind, text):
    from datetime import datetime, timezone
    key = f"uploads/fleet={fleet_id}/{kind}/{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    _s3.put_object(Bucket=BUCKET, Key=key, Body=text.encode(), ContentType="text/csv")
    return key
