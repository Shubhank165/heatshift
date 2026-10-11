"""Heat-stress engine: estimated outdoor WBGT and risk bands.

WBGT (wet-bulb globe temperature) is the occupational standard for heat stress
(ISO 7243 / ACGIH). We estimate it from forecast data:

    WBGT ~= 0.7 * Tw + 0.2 * Tg + 0.1 * Ta

  Tw  wet-bulb temperature (Open-Meteo, or Stull 2011 from Ta + RH)
  Tg  black-globe temperature, Hunter & Minyard (1999):
      Tg = 0.01498*SR + 1.184*Ta - 0.0789*RH - 2.739

This is a screening estimate, not a measurement.
"""
import math

# Bands for moderate work (riding, walking with parcels), acclimatized workers,
# following the ACGIH TLV work/rest table. rest = minutes of rest per hour.
BANDS = [
    # name, min WBGT (inclusive), rest minutes per hour
    ("SAFE", -99.0, 0),
    ("CAUTION", 28.0, 15),
    ("DANGER", 29.0, 30),
    ("SEVERE", 30.0, 45),
    ("EXTREME", 31.5, 60),  # 60 = no outdoor work
]
BAND_ORDER = {name: i for i, (name, _, _) in enumerate(BANDS)}
REST_MIN = {name: rest for name, _, rest in BANDS}


def stull_wet_bulb(ta, rh):
    """Wet-bulb temperature (C) from air temperature (C) and RH (%), Stull 2011."""
    return (
        ta * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(ta + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def globe_temp(ta, rh, sr):
    tg = 0.01498 * sr + 1.184 * ta - 0.0789 * rh - 2.739
    return max(tg, ta - 2.0)


def wbgt(ta, rh, sr, tw=None):
    if tw is None:
        tw = stull_wet_bulb(ta, rh)
    return 0.7 * tw + 0.2 * globe_temp(ta, rh, sr) + 0.1 * ta


def band_for(wbgt_c, offset=0.0):
    """Risk band for a WBGT value. `offset` lowers thresholds (e.g. 2.5 for
    workers who are not yet acclimatized)."""
    name = "SAFE"
    for band, lo, _ in BANDS:
        if wbgt_c >= lo - offset:
            name = band
    return name


def worse(a, b):
    return a if BAND_ORDER[a] >= BAND_ORDER[b] else b


def hourly_risk(hourly):
    """hourly: list of dicts with hour, ta, rh, sr, ws, tw (tw may be None).
    Returns the same rows enriched with wbgt and band."""
    out = []
    for row in hourly:
        w = wbgt(row["ta"], row["rh"], row["sr"], row.get("tw"))
        out.append({**row, "wbgt": round(w, 1), "band": band_for(w)})
    return out
