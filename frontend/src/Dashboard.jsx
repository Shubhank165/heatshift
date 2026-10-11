import React, { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from "react-leaflet";
import { api, BANDS, inr } from "./api.js";

const HOURS = Array.from({ length: 16 }, (_, i) => i + 6); // 06..21

function BandPill({ band, children }) {
  const b = BANDS[band] || BANDS.SAFE;
  return (
    <span className="pill" style={{ background: b.color }}>
      {children || b.label}
    </span>
  );
}

function Kpi({ label, value, sub, tone }) {
  return (
    <div className={`kpi ${tone || ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function Heatmap({ plan, hour, setHour }) {
  return (
    <div className="heatmap">
      <div className="hm-row hm-head">
        <div className="hm-zone" />
        {HOURS.map((h) => (
          <button key={h} className={`hm-hour ${hour === h ? "sel" : ""}`} onClick={() => setHour(h)}>
            {String(h).padStart(2, "0")}
          </button>
        ))}
      </div>
      {plan.zones.map((z) => {
        const rows = Object.fromEntries((plan.risk[z.id] || []).map((r) => [r.hour, r]));
        return (
          <div className="hm-row" key={z.id}>
            <div className="hm-zone" title={z.name}>{z.name}</div>
            {HOURS.map((h) => {
              const r = rows[h];
              const b = BANDS[r?.band] || BANDS.SAFE;
              return (
                <div
                  key={h}
                  className={`hm-cell ${hour === h ? "sel" : ""}`}
                  style={{ background: b.color }}
                  title={r ? `${z.name} ${h}:00 · WBGT ${r.wbgt}°C · ${b.label} (${b.rest}) · air ${r.ta}°C, RH ${r.rh}%` : ""}
                  onClick={() => setHour(h)}
                >
                  {r ? Math.round(r.wbgt) : ""}
                </div>
              );
            })}
          </div>
        );
      })}
      <div className="legend">
        {Object.entries(BANDS).map(([k, b]) => (
          <span key={k}><i style={{ background: b.color }} />{b.label} · {b.rest}</span>
        ))}
      </div>
      <p className="muted small">Cells show estimated WBGT (°C) per hour. Click an hour to update the map.</p>
    </div>
  );
}

function FitZones({ zones }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(zones.map((z) => [z.lat, z.lon]), { padding: [40, 40] });
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(map.getContainer());
    return () => ro.disconnect();
  }, [map]);
  return null;
}

function ZoneMap({ fleet, plan, hour }) {
  const center = [fleet.meta.hub.lat, fleet.meta.hub.lon];
  return (
    <MapContainer center={center} zoom={11} scrollWheelZoom wheelPxPerZoomLevel={90} zoomSnap={0.5}
      zoomDelta={0.5} touchZoom doubleClickZoom className="map">
      <FitZones zones={plan.zones} />
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {plan.zones.map((z) => {
        const r = (plan.risk[z.id] || []).find((x) => x.hour === hour);
        const b = BANDS[r?.band] || BANDS.SAFE;
        return (
          <CircleMarker key={z.id} center={[z.lat, z.lon]} radius={28}
            pathOptions={{ color: b.color, fillColor: b.color, fillOpacity: 0.45, weight: 2 }}>
            <Tooltip direction="top">
              <b>{z.name}</b><br />{String(hour).padStart(2, "0")}:00 · {b.label} · WBGT {r?.wbgt}°C<br />
              {z.workers} workers · {z.nearest_rest ? `cool point ${z.nearest_rest.distance_km} km` : "no cool point"}
            </Tooltip>
          </CircleMarker>
        );
      })}
      {fleet.rest_points.map((p) => (
        <CircleMarker key={p.id} center={[p.lat, p.lon]} radius={p.designated ? 7 : 4}
          pathOptions={{ color: p.designated ? "#0b6e4f" : "#667085", fillColor: p.designated ? "#19a974" : "#fff", fillOpacity: 1, weight: 2 }}>
          <Tooltip>{p.designated ? "Rest point: " : "Candidate: "}{p.name}<br /><span className="small">{p.category}</span></Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}

const STEP_ICON = { done: "✓", running: "", retrying: "↻", failed: "✕", pending: "" };

function RunProgress({ run, onClose }) {
  const steps = run.steps || [];
  const done = steps.filter((s) => s.state === "done").length;
  const running = steps.some((s) => s.state === "running" || s.state === "retrying");
  const pct = run.status === "SUCCEEDED" ? 100 : Math.round(((done + (running ? 0.5 : 0)) / Math.max(steps.length, 4)) * 100);
  const finished = run.status !== "RUNNING" && run.status !== "STARTING";
  return (
    <section className={`card run ${run.status === "SUCCEEDED" ? "ok" : ""} ${run.error || run.status === "FAILED" ? "bad" : ""}`}>
      <div className="run-head">
        <b>
          {run.status === "SUCCEEDED" ? `Plan ready for ${run.date}` :
            run.error || run.status === "FAILED" ? "Planning failed" : "Planning tomorrow with the latest forecast…"}
        </b>
        <span className="muted small">
          Step Functions · {run.elapsed != null ? `${run.elapsed.toFixed(1)}s` : ""}
        </span>
        {finished && <button className="btn ghost small-btn" onClick={onClose}>Close</button>}
      </div>
      <div className="bar"><div className="bar-fill" style={{ width: `${pct}%` }} /></div>
      <ol className="steps">
        {(steps.length ? steps : [{ id: "start", label: "Starting workflow", state: "running" }]).map((s) => (
          <li key={s.id} className={`step ${s.state}`}>
            <span className="step-dot">{STEP_ICON[s.state]}</span>
            <span>{s.label}</span>
            <span className="muted small step-state">{s.state === "pending" ? "" : s.state}</span>
          </li>
        ))}
      </ol>
      {run.error && <div className="error-inline">{run.error}</div>}
      {run.status === "SUCCEEDED" && run.kpis && (
        <div className="muted small">
          Peak {BANDS[run.kpis.peak_band]?.label} · WBGT {run.kpis.peak_wbgt}°C · {run.kpis.shifts_changed}/{run.kpis.workers} shifts
          restructured · {run.kpis.new_joiners} new joiners · now showing this plan below.
        </div>
      )}
    </section>
  );
}

const ACTION_ICON = { stop_window: "⛔", acclimatization: "🧑‍🎓", coverage_gap: "📍", reslot: "📦", supplies: "💧" };

function Actions({ plan }) {
  return (
    <ol className="actions">
      {plan.actions.map((a, i) => (
        <li key={i} className={`action ${a.kind}`}>
          <span className="a-icon">{ACTION_ICON[a.kind] || "•"}</span>
          <div>
            <div className="a-title">{a.title}</div>
            <div className="a-detail">{a.detail}</div>
            {a.customer_message && <div className="a-quote">Customer message: “{a.customer_message}”</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function Workers({ plan }) {
  const [filter, setFilter] = useState("all");
  const cards = plan.cards.filter((c) => filter === "all" || (filter === "new" ? c.new_joiner : c.zone === filter));
  return (
    <div>
      <div className="row gap">
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All workers ({plan.cards.length})</option>
          <option value="new">New joiners</option>
          {plan.zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
        </select>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Worker</th><th>Zone</th><th>Usual shift</th><th>Heat-safe shift</th><th>Breaks</th><th>Peak</th><th>Guaranteed pay</th><th /></tr>
          </thead>
          <tbody>
            {cards.map((c) => (
              <tr key={c.worker_id}>
                <td>{c.name} <span className="muted small">{c.worker_id} · {c.type}</span>{c.new_joiner && <span className="tag">new</span>}</td>
                <td>{c.zone_name}</td>
                <td className="muted">{c.original_shift}</td>
                <td className={c.changed ? "changed" : ""}>{c.shift}</td>
                <td>{c.breaks.length}</td>
                <td><BandPill band={c.peak_band} /></td>
                <td>{inr(c.guaranteed_pay_inr)}</td>
                <td><a href={`#/worker/${c.worker_id}?date=${plan.date}`}>card →</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Dispatch({ plan }) {
  const [zone, setZone] = useState(plan.zones[0]?.id);
  const [time, setTime] = useState("13:30");
  const [worker, setWorker] = useState("");
  const [res, setRes] = useState(null);
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState("");
  const at = `${plan.date}T${time}`;
  const check = async () => { setMsg(""); setRes(await api.dispatchCheck(zone, at, worker || undefined)); };
  const override = async () => {
    await api.override({ zone, at, reason, job: "manual" });
    setMsg("Override logged. It will appear in the compliance report.");
    setReason("");
  };
  return (
    <div className="dispatch">
      <p className="muted">This is the check a dispatch system calls before assigning a job:
        <code> GET /fleets/{"{id}"}/dispatch-check?zone=…&at=…</code></p>
      <div className="row gap wrap">
        <select value={zone} onChange={(e) => setZone(e.target.value)}>
          {plan.zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
        </select>
        <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        <input placeholder="Worker ID (optional)" value={worker} onChange={(e) => setWorker(e.target.value)} />
        <button className="btn" onClick={check}>Check assignment</button>
      </div>
      {res && (
        <div className={`verdict ${res.allowed ? "ok" : "blocked"}`}>
          <b>{res.allowed ? "✅ Allowed" : "⛔ Blocked"}</b> · <BandPill band={res.band} /> WBGT {res.wbgt}°C
          {res.reason && <div>{res.reason}</div>}
          {!res.allowed && (
            <div className="row gap wrap" style={{ marginTop: 8 }}>
              <input style={{ flex: 1, minWidth: 220 }} placeholder="Critical job only, e.g. medicine delivery (logged)"
                value={reason} onChange={(e) => setReason(e.target.value)} />
              <button className="btn ghost" disabled={!reason} onClick={override}>Log manager override</button>
            </div>
          )}
        </div>
      )}
      {msg && <p className="muted">{msg}</p>}
      <p className="muted small">Workers cannot opt in to work during a stop window, and no setting adds heat surge pay.</p>
    </div>
  );
}

function Live({ plan, reload }) {
  return (
    <div className="two">
      <div>
        <h4>Worker check-ins</h4>
        {plan.checkins.length === 0 && <p className="muted">No check-ins yet.</p>}
        <ul className="feed">
          {[...plan.checkins].reverse().map((c, i) => (
            <li key={i} className={c.status}>
              {c.status === "unwell" ? "🆘" : "✅"} <b>{c.name || c.worker_id}</b> {c.status === "unwell" ? "reported feeling unwell" : "checked in OK"}
              <span className="muted small"> · {c.zone} · {c.created_at.slice(11, 16)}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h4>Override log</h4>
        {plan.overrides.length === 0 && <p className="muted">No overrides. Good.</p>}
        <ul className="feed">
          {plan.overrides.map((o, i) => (
            <li key={i}>⚠ {o.zone} at {o.at.slice(11)}: {o.reason} <span className="muted small">· {o.by}</span></li>
          ))}
        </ul>
      </div>
      <button className="btn ghost" onClick={reload}>Refresh</button>
    </div>
  );
}

function Policy({ fleet }) {
  const p = fleet.meta.policy;
  const rows = [
    ["Stop outdoor work at", p.stop_band],
    ["New joiner period", `${p.acclimatization_days} days, thresholds −${p.acclimatization_offset_c}°C WBGT`],
    ["Operating window", `${p.op_start}:00–${p.op_end}:00`],
    ["Breaks are paid", p.paid_breaks ? "Yes" : "No"],
    ["Planned hours guaranteed", p.guarantee_planned_hours ? "Yes" : "No"],
    ["Hourly rate used for costs", inr(p.hourly_rate_inr)],
    ["Max distance to a cool point", `${p.max_rest_km} km`],
  ];
  return (
    <div className="policy">
      <table><tbody>{rows.map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td><b>{v}</b></td></tr>)}</tbody></table>
      <div className="locked">
        🔒 <b>Heat surge pay: off, and not configurable.</b> Paying more for deliveries in extreme heat rewards the most
        financially desperate workers for taking the most risk. HeatShift moves the work, not the risk: breaks are paid and
        planned hours are guaranteed instead.
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [fleet, setFleet] = useState(null);
  const [date, setDate] = useState(null);
  const [plan, setPlan] = useState(null);
  const [hour, setHour] = useState(13);
  const [tab, setTab] = useState("actions");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [run, setRun] = useState(null);
  const poll = useRef(null);
  useEffect(() => () => clearTimeout(poll.current), []);

  const loadFleet = async () => {
    const f = await api.fleet();
    setFleet(f);
    if (!date && f.plans.length) {
      const replay = f.plans.find((p) => p.date === "2026-05-28");
      setDate((replay || f.plans[f.plans.length - 1]).date);
    }
  };
  const loadPlan = async (d = date) => { if (d) setPlan(await api.plan(d)); };

  useEffect(() => { loadFleet().catch((e) => setErr(e.message)); }, []);
  useEffect(() => { loadPlan().catch((e) => setErr(e.message)); }, [date]);

  const approve = async () => {
    setBusy("approve");
    try { await api.approve(date); await loadPlan(); } catch (e) { alert(e.message); } finally { setBusy(""); }
  };
  const runTomorrow = async () => {
    clearTimeout(poll.current);
    setBusy("run");
    const t0 = Date.now();
    setRun({ status: "STARTING", steps: [], elapsed: 0 });
    const fail = (e) => { setRun((r) => ({ ...r, status: "FAILED", error: e.message || String(e) })); setBusy(""); };
    try {
      const { run: id } = await api.runPlan();
      const tick = async () => {
        try {
          const r = await api.run(id);
          const elapsed = (Date.now() - t0) / 1000;
          setRun({ ...r, elapsed });
          if (r.status === "RUNNING") {
            if (elapsed > 120) return fail(new Error("Timed out waiting for the workflow"));
            poll.current = setTimeout(tick, 700);
            return;
          }
          if (r.status !== "SUCCEEDED") return fail(new Error(`Workflow ${r.status.toLowerCase()}`));
          await loadFleet();
          setDate(r.date);
          await loadPlan(r.date);
          setBusy("");
        } catch (e) { fail(e); }
      };
      tick();
    } catch (e) { fail(e); }
  };

  const k = plan?.kpis;
  const peakBand = useMemo(() => BANDS[k?.peak_band] || BANDS.SAFE, [k]);

  if (err) return <div className="page"><div className="error">Could not load: {err}</div></div>;
  if (!fleet || !plan) return <div className="page"><div className="loading">Loading HeatShift…</div></div>;

  return (
    <div className="page">
      <header className="top">
        <div className="brand">🌡️ HeatShift <span className="muted">· {fleet.meta.name}</span></div>
        <div className="row gap wrap">
          <select value={date} onChange={(e) => setDate(e.target.value)}>
            {fleet.plans.map((p) => (
              <option key={p.date} value={p.date}>
                {p.date}{p.date === "2026-05-28" ? " (heatwave replay)" : ""} · {p.peak_band}
              </option>
            ))}
          </select>
          <button className="btn ghost" onClick={runTomorrow} disabled={busy === "run"}>
            {busy === "run" ? "Planning…" : "Re-plan tomorrow"}
          </button>
          {plan.status === "APPROVED" ? (
            <span className="approved">✓ Approved {plan.approved_at?.slice(11, 16)}</span>
          ) : (
            <button className="btn" onClick={approve} disabled={busy === "approve"}>Approve plan</button>
          )}
        </div>
      </header>

      {run && <RunProgress run={run} onClose={() => setRun(null)} />}

      <section className="banner" style={{ borderColor: peakBand.color }}>
        <BandPill band={k.peak_band} />
        <div>
          <b>Plan for {new Date(plan.date + "T00:00").toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</b>
          <div className="muted">
            {k.stop_window ? <>No outdoor work <b>{k.stop_window}</b> · peak WBGT {k.peak_wbgt}°C</> : <>No stop window needed · peak WBGT {k.peak_wbgt}°C</>}
            {" · "}generated {plan.generated_at?.replace("T", " ")}
          </div>
        </div>
      </section>

      <section className="kpis">
        <Kpi label="Worker-hours in Danger or worse" value={<>{k.risk_hours_original} → <span className="good">{k.risk_hours_planned}</span></>} sub="usual shifts → heat-safe plan" />
        <Kpi label="Shifts restructured" value={`${k.shifts_changed} / ${k.workers}`} sub={`${k.new_joiners} new joiners on stricter limits`} />
        <Kpi label="Capacity change" value={`${k.capacity_change_pct}%`} sub={`${k.hours_lost} hours lost`} />
        <Kpi label="Cost of protection" value={inr(k.cost_of_protection_inr)} sub="paid breaks + guaranteed hours" />
        <Kpi label="Supplies" value={`${k.water_l} L`} sub={`water · ${k.ors} ORS sachets`} />
      </section>

      <section className="grid">
        <div className="card"><h3>Zones at {String(hour).padStart(2, "0")}:00</h3><ZoneMap fleet={fleet} plan={plan} hour={hour} /></div>
        <div className="card"><h3>Heat stress by zone and hour</h3><Heatmap plan={plan} hour={hour} setHour={setHour} /></div>
      </section>

      <section className="card">
        <nav className="tabs">
          {[["actions", "Recommended actions"], ["workers", "Workers"], ["dispatch", "Dispatch check"], ["live", "Live"], ["policy", "Policy"]].map(([id, label]) => (
            <button key={id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>{label}</button>
          ))}
        </nav>
        {tab === "actions" && <Actions plan={plan} />}
        {tab === "workers" && <Workers plan={plan} />}
        {tab === "dispatch" && <Dispatch plan={plan} />}
        {tab === "live" && <Live plan={plan} reload={() => loadPlan()} />}
        {tab === "policy" && <Policy fleet={fleet} />}
      </section>

      <footer className="muted small">
        Weather: Open-Meteo (real forecasts and archived forecasts) · Places: Amazon Location Service · Workers: synthetic demo roster.
        WBGT is a screening estimate, not medical advice.
      </footer>
    </div>
  );
}
