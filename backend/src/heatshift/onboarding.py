"""Roster import: a fleet uploads a CSV exported from its HR / workforce system.
Rows are validated, then upserted as WORKER# items. Bad rows are reported, not imported."""
import csv
import io
import re
from datetime import date

COLUMNS = ["worker_id", "name", "phone", "zone", "shift_start", "shift_end", "join_date", "type", "language", "channel"]
REQUIRED = ["worker_id", "name", "zone", "shift_start", "shift_end", "join_date"]
TYPES = {"gig", "employee", "contract"}
LANGUAGES = {"hi", "en"}
CHANNELS = {"whatsapp", "sms", "voice", "app"}


def _hour(v):
    m = re.fullmatch(r"(\d{1,2})(?::00)?", v.strip())
    if not m or not 0 <= int(m.group(1)) <= 24:
        raise ValueError(f"'{v}' is not a whole hour like 07:00")
    return int(m.group(1))


def _phone(v):
    digits = re.sub(r"\D", "", v)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError(f"'{v}' is not a valid Indian mobile number")
    return "+91" + digits


def parse_roster(text, zones):
    """Returns (workers, errors). Zones may be given by id or by name."""
    by_key = {z["id"].lower(): z["id"] for z in zones} | {z["name"].lower(): z["id"] for z in zones}
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in headers]
    if missing:
        return [], [{"row": 1, "error": f"missing column(s): {', '.join(missing)}"}]

    workers, errors, seen = [], [], set()
    for i, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        try:
            for c in REQUIRED:
                if not row.get(c):
                    raise ValueError(f"{c} is empty")
            wid = row["worker_id"]
            if not re.fullmatch(r"\w+", wid):
                raise ValueError(f"worker_id '{wid}' may only contain letters, digits and _")
            if wid in seen:
                raise ValueError(f"duplicate worker_id {wid}")
            zone = by_key.get(row["zone"].lower())
            if not zone:
                raise ValueError(f"unknown zone '{row['zone']}'")
            start, end = _hour(row["shift_start"]), _hour(row["shift_end"])
            if end <= start:
                raise ValueError("shift_end must be after shift_start")
            joined = date.fromisoformat(row["join_date"]).isoformat()
            w = {"id": wid, "name": row["name"], "zone": zone, "shift_start": start, "shift_end": end,
                 "join_date": joined, "type": (row.get("type") or "employee").lower(),
                 "language": (row.get("language") or "hi").lower(),
                 "channel": (row.get("channel") or "whatsapp").lower()}
            if w["type"] not in TYPES:
                raise ValueError(f"type must be one of {', '.join(sorted(TYPES))}")
            if w["language"] not in LANGUAGES:
                raise ValueError(f"language must be one of {', '.join(sorted(LANGUAGES))}")
            if w["channel"] not in CHANNELS:
                raise ValueError(f"channel must be one of {', '.join(sorted(CHANNELS))}")
            if row.get("phone"):
                w["phone"] = _phone(row["phone"])
            elif w["channel"] in ("whatsapp", "sms", "voice"):
                raise ValueError(f"phone is required for channel {w['channel']}")
        except ValueError as e:
            errors.append({"row": i, "worker_id": row.get("worker_id"), "error": str(e)})
            continue
        seen.add(wid)
        workers.append(w)
    return workers, errors
