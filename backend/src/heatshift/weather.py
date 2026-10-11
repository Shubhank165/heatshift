"""Open-Meteo client (free, no API key). One request covers every zone of a fleet."""
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
HOURLY = "temperature_2m,relative_humidity_2m,wet_bulb_temperature_2m,shortwave_radiation,wind_speed_10m"


def today_ist():
    return datetime.now(IST).date()


def fetch_hourly(zones, plan_date):
    """Returns (source_url, raw_json_list)."""
    d = date.fromisoformat(plan_date)
    base = FORECAST_URL if d >= today_ist() - timedelta(days=1) else HISTORICAL_URL
    params = {
        "latitude": ",".join(str(z["lat"]) for z in zones),
        "longitude": ",".join(str(z["lon"]) for z in zones),
        "hourly": HOURLY,
        "start_date": plan_date,
        "end_date": plan_date,
        "timezone": "Asia/Kolkata",
    }
    url = f"{base}?{urllib.parse.urlencode(params)}"
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                data = json.loads(resp.read())
            return url, data if isinstance(data, list) else [data]
        except Exception as e:  # retry transient network errors
            last = e
    raise RuntimeError(f"Open-Meteo fetch failed: {last}")


def parse(zones, raw):
    """-> {zone_id: [{hour, ta, rh, tw, sr, ws}, ...]}"""
    out = {}
    for z, loc in zip(zones, raw):
        h = loc["hourly"]
        rows = []
        for i, t in enumerate(h["time"]):
            ta, rh = h["temperature_2m"][i], h["relative_humidity_2m"][i]
            if ta is None or rh is None:
                continue
            rows.append({
                "hour": int(t[11:13]),
                "ta": ta,
                "rh": rh,
                "tw": (h.get("wet_bulb_temperature_2m") or [None] * len(h["time"]))[i],
                "sr": h["shortwave_radiation"][i] or 0.0,
                "ws": h["wind_speed_10m"][i] or 0.0,
            })
        out[z["id"]] = rows
    return out
