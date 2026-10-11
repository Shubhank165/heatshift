"""Demo fleet: a fictional delivery hub in Gurugram with a synthetic roster.
Weather and places are real; workers are generated."""
import random
from datetime import date, timedelta

FLEET_ID = "demo-gurugram"

META = {
    "id": FLEET_ID,
    "name": "Demo Logistics · Gurugram Hub",
    "city": "Gurugram",
    "hub": {"lat": 28.4400, "lon": 77.0410},
}

ZONES = [
    {"id": "Z1", "name": "Cyber City", "lat": 28.4950, "lon": 77.0890},
    {"id": "Z2", "name": "Sector 29 / MG Road", "lat": 28.4690, "lon": 77.0640},
    {"id": "Z3", "name": "Sohna Road", "lat": 28.4120, "lon": 77.0420},
    {"id": "Z4", "name": "Golf Course Road", "lat": 28.4380, "lon": 77.1000},
    {"id": "Z5", "name": "Palam Vihar", "lat": 28.5080, "lon": 77.0330},
    {"id": "Z6", "name": "New Gurugram (Sec 82)", "lat": 28.3920, "lon": 76.9640},
]

FIRST = ["Ravi", "Amit", "Suresh", "Mohit", "Deepak", "Vikas", "Rahul", "Sunil", "Anil", "Manoj",
         "Pankaj", "Rakesh", "Sanjay", "Ajay", "Imran", "Arjun", "Rohit", "Naveen", "Gaurav", "Sachin",
         "Pooja", "Neha", "Kiran", "Sunita", "Asif", "Ramesh", "Dinesh", "Karan", "Vijay", "Harish"]
LAST = ["K.", "S.", "Y.", "M.", "R.", "P.", "G.", "T.", "B.", "D."]
SHIFTS = [(7, 15), (9, 17), (11, 19), (13, 21)]


def roster(per_zone=20, seed=42, new_joiner_anchors=("2026-05-28", "2026-10-12")):
    rng = random.Random(seed)
    workers, n = [], 0
    for z in ZONES:
        for _ in range(per_zone):
            n += 1
            s, e = rng.choice(SHIFTS)
            if rng.random() < 0.12:
                # recently joined relative to one of the demo dates
                anchor = date.fromisoformat(rng.choice(new_joiner_anchors))
                joined = anchor - timedelta(days=rng.randint(1, 12))
            else:
                joined = date(2025, 1, 1) + timedelta(days=rng.randint(0, 420))
            workers.append({
                "id": f"W{n:03d}",
                "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                "zone": z["id"],
                "shift_start": s,
                "shift_end": e,
                "join_date": joined.isoformat(),
                "type": "gig" if rng.random() < 0.4 else "employee",
            })
    return workers
