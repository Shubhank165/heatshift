export const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
export const FLEET = import.meta.env.VITE_FLEET_ID || "demo-gurugram";

async function call(method, path, body) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export const api = {
  fleet: () => call("GET", `/fleets/${FLEET}`),
  plan: (date) => call("GET", `/fleets/${FLEET}/plans/${date}`),
  approve: (date) => call("POST", `/fleets/${FLEET}/plans/${date}/approve`, { by: "manager" }),
  runPlan: (date) => call("POST", `/fleets/${FLEET}/plans`, date ? { date } : {}),
  run: (id) => call("GET", `/fleets/${FLEET}/runs/${id}`),
  card: (wid, date) => call("GET", `/fleets/${FLEET}/workers/${wid}/card?date=${date}`),
  dispatchCheck: (zone, at, worker) =>
    call("GET", `/fleets/${FLEET}/dispatch-check?zone=${zone}&at=${at}${worker ? `&worker=${worker}` : ""}`),
  override: (body) => call("POST", `/fleets/${FLEET}/overrides`, body),
  checkin: (body) => call("POST", `/fleets/${FLEET}/checkins`, body),
  policy: (body) => call("PUT", `/fleets/${FLEET}/policy`, body),
};

export const BANDS = {
  SAFE: { color: "#3f9b5a", label: "Safe", rest: "Normal work" },
  CAUTION: { color: "#e8b923", label: "Caution", rest: "45 min work / 15 rest" },
  DANGER: { color: "#ef8a2c", label: "Danger", rest: "30 / 30" },
  SEVERE: { color: "#d9452b", label: "Severe", rest: "15 / 45" },
  EXTREME: { color: "#7a1a3a", label: "Extreme", rest: "No outdoor work" },
};

export const inr = (n) => `₹${Math.round(n).toLocaleString("en-IN")}`;
