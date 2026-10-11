"""Worker messages for an approved plan, in the worker's language and channel.
In production these go out through AWS End User Messaging (WhatsApp / SMS), Amazon Polly
voice calls, or the fleet's own app via webhook. Here they are built and stored as an outbox."""
import zlib
from collections import Counter
from datetime import date

T = {
    "en": {
        "stop": "🔥 No outdoor work {stop} (extreme heat)",
        "shift": "Your shift: {shift}",
        "changed": " (changed for heat safety)",
        "breaks": "Paid breaks: {breaks}",
        "rest": "Cool point: {name} ({dist})",
        "norest": "Cool point: ask your hub lead for the nearest shade",
        "water": "Drink {water} L of water through the day",
        "pay": "Today's pay ₹{pay} guaranteed",
        "new": "You're new: stricter heat limits for your first 2 weeks",
        "buttons": ["I'm OK", "I feel unwell"],
        "voice": "Hello {name}. {stopv}Your shift is {shift}. Your full pay of {pay} rupees is guaranteed. "
                 "If you feel unwell, press 1.",
        "stopv": "Tomorrow there is no outdoor work from {stop}. ",
        "sms": "HeatShift {day}: {stopsms}Shift {shift}. Breaks {breaks}. Pay Rs{pay} guaranteed. Unwell? Reply 2. {link}",
        "stopsms": "NO outdoor work {stop}. ",
    },
    "hi": {
        "stop": "🔥 {stop} बाहर काम बंद (बहुत ज़्यादा गर्मी)",
        "shift": "आपकी शिफ्ट: {shift}",
        "changed": " (गर्मी की वजह से बदली गई)",
        "breaks": "पेड ब्रेक: {breaks}",
        "rest": "ठंडी जगह: {name} ({dist})",
        "norest": "ठंडी जगह: नज़दीकी छाँव के लिए हब लीड से पूछें",
        "water": "पानी: दिन में {water} लीटर",
        "pay": "आज की पूरी पेमेंट ₹{pay} पक्की",
        "new": "आप नए हैं: पहले 2 हफ़्ते गर्मी की सीमा ज़्यादा सख़्त है",
        "buttons": ["मैं ठीक हूँ", "तबीयत ख़राब है"],
        "voice": "नमस्ते {name}। {stopv}आपकी शिफ्ट {shift} है। आपकी पूरी पेमेंट {pay} रुपये पक्की है। "
                 "तबीयत ख़राब हो तो 1 दबाएँ।",
        "stopv": "कल {stop} बाहर काम बंद रहेगा। ",
        "sms": "HeatShift {day}: {stopsms}Shift {shift}. Break {breaks}. Pay Rs{pay} pakki. Tabiyat kharab? 2 bhejein. {link}",
        "stopsms": "{stop} bahar kaam BAND. ",
    },
}

MAX_REST_KM = 3.0  # never point a worker at a "cool point" further than this

ROUTE = {
    "whatsapp": "AWS End User Messaging Social (WhatsApp template + quick replies)",
    "sms": "AWS End User Messaging SMS",
    "voice": "Outbound call, Amazon Polly Hindi/English voice",
    "app": "Webhook to the fleet's own rider app (push notification)",
}


def _defaults(w):
    """Demo roster workers have no contact details; derive stable synthetic ones."""
    h = zlib.crc32(w["id"].encode())
    out = dict(w)
    out.setdefault("language", "en" if h % 10 < 3 else "hi")
    out.setdefault("channel", "app" if w.get("type") == "gig" and h % 3 == 0 else
                   "sms" if h % 10 == 7 else "voice" if h % 20 == 3 else "whatsapp")
    out.setdefault("phone", f"+9198{h % 100000000:08d}")
    return out


def mask(phone):
    return f"{phone[:5]}••••{phone[-4:]}" if phone else ""


def build_outbox(plan, workers, app_url):
    by_id = {w["id"]: _defaults(w) for w in workers}
    day = date.fromisoformat(plan["date"]).strftime("%a %d %b")
    messages = []
    for c in plan["cards"]:
        w = by_id.get(c["worker_id"], _defaults({"id": c["worker_id"], "type": c.get("type")}))
        lang, ch = w["language"], w["channel"]
        t = T[lang]
        link = f"{app_url.rstrip('/')}/#/worker/{c['worker_id']}?date={plan['date']}" if app_url else ""
        breaks = ", ".join(b.split("–")[0] for b in c["breaks"]) or "—"
        rest = c.get("nearest_rest")
        if ch == "voice":
            body = t["voice"].format(name=c["name"].split()[0], shift=c["shift"], pay=c["guaranteed_pay_inr"],
                                     stopv=t["stopv"].format(stop=c["stop_window"]) if c["stop_window"] else "")
            buttons = ["1", "2"]
        elif ch == "sms":
            body = t["sms"].format(day=day, shift=c["shift"], breaks=breaks, pay=c["guaranteed_pay_inr"], link=link,
                                   stopsms=t["stopsms"].format(stop=c["stop_window"]) if c["stop_window"] else "")
            buttons = []
        else:
            lines = [f"🌡️ HeatShift · {day}"]
            if c["stop_window"]:
                lines.append(t["stop"].format(stop=c["stop_window"]))
            lines.append(t["shift"].format(shift=c["shift"]) + (t["changed"] if c["changed"] else ""))
            if c["breaks"]:
                lines.append(t["breaks"].format(breaks=breaks))
            if rest and rest["distance_km"] <= MAX_REST_KM:
                km = rest["distance_km"]
                lines.append(t["rest"].format(name=rest["name"], dist=f"{max(50, round(km * 1000, -1)):.0f} m" if km < 1 else f"{km} km"))
            else:
                lines.append(t["norest"])
            lines.append(t["water"].format(water=c["water_l"]))
            lines.append(t["pay"].format(pay=c["guaranteed_pay_inr"]))
            if c["new_joiner"]:
                lines.append(t["new"])
            if link:
                lines.append(link)
            body = "\n".join(lines)
            buttons = t["buttons"]
        messages.append({"worker_id": c["worker_id"], "name": c["name"], "zone": c["zone_name"],
                         "channel": ch, "language": lang, "to": mask(w.get("phone")), "via": ROUTE[ch],
                         "body": body, "buttons": buttons, "priority": "high" if c["stop_window"] else "normal",
                         "status": "QUEUED"})
    counts = Counter(m["channel"] for m in messages)
    return {"date": plan["date"], "messages": messages, "by_channel": dict(counts),
            "by_language": dict(Counter(m["language"] for m in messages))}
