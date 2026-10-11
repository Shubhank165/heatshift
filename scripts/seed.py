"""Seed the demo fleet: zones, synthetic roster, and real rest-point candidates
from Amazon Location Service. Usage: python scripts/seed.py <table-name>"""
import json
import sys
from decimal import Decimal
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))
from heatshift import demo  # noqa: E402
from heatshift.planner import DEFAULT_POLICY, haversine_km  # noqa: E402

REGION = "ap-south-1"
COOL_CATEGORIES = ["shopping_mall", "petrol_gasoline_station"]
# Zones where the demo hub has already set up partner rest points; the others
# are left uncovered so the coverage-gap analysis has something to find.
DESIGNATED_ZONES = {"Z1", "Z2", "Z4"}


def ddb_item(obj):
    return json.loads(json.dumps(obj), parse_float=Decimal)


def search_cool_points(places, zone):
    cats = list(COOL_CATEGORIES)
    while cats:
        try:
            r = places.search_nearby(QueryPosition=[zone["lon"], zone["lat"]], QueryRadius=3000,
                                     MaxResults=20, Filter={"IncludeCategories": cats})
            break
        except places.exceptions.ValidationException as e:
            bad = [c for c in cats if c in str(e)]
            if not bad:
                raise
            cats = [c for c in cats if c not in bad]
    else:
        return []
    out = []
    for i in r.get("ResultItems", []):
        lon, lat = i["Position"]
        out.append({
            "place_id": i["PlaceId"],
            "name": i["Title"],
            "lat": lat,
            "lon": lon,
            "category": (i.get("Categories") or [{}])[0].get("Id", "place"),
            "address": i.get("Address", {}).get("Label", ""),
            "source": "Amazon Location Service",
        })
    return out


def main(table_name):
    table = boto3.resource("dynamodb", region_name=REGION).Table(table_name)
    places = boto3.client("geo-places", region_name=REGION)
    pk = f"FLEET#{demo.FLEET_ID}"

    with table.batch_writer() as batch:
        batch.put_item(Item=ddb_item({**demo.META, "policy": DEFAULT_POLICY, "pk": pk, "sk": "META"}))
        for z in demo.ZONES:
            batch.put_item(Item=ddb_item({**z, "pk": pk, "sk": f"ZONE#{z['id']}"}))
        workers = demo.roster()
        for w in workers:
            batch.put_item(Item=ddb_item({**w, "pk": pk, "sk": f"WORKER#{w['id']}"}))

        seen, n = set(), 0
        for z in demo.ZONES:
            pts = search_cool_points(places, z)
            pts.sort(key=lambda p: haversine_km(z["lat"], z["lon"], p["lat"], p["lon"]))
            for i, p in enumerate(pts[:6]):
                if p["place_id"] in seen:
                    continue
                seen.add(p["place_id"])
                n += 1
                designated = z["id"] in DESIGNATED_ZONES and i == 0
                batch.put_item(Item=ddb_item({**p, "id": f"R{n:02d}", "zone": z["id"],
                                              "designated": designated, "pk": pk, "sk": f"REST#R{n:02d}"}))
            print(f"{z['id']} {z['name']}: {len(pts)} candidates; nearest "
                  + (f"{pts[0]['name']} ({pts[0]['category']})" if pts else "none"))
    print(f"seeded {len(workers)} workers, {n} rest-point candidates")


if __name__ == "__main__":
    main(sys.argv[1])
