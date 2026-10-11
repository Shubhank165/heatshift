import React, { useEffect, useState } from "react";
import { api, BANDS } from "./api.js";

export default function WorkerCard({ workerId, date }) {
  const [card, setCard] = useState(null);
  const [err, setErr] = useState("");
  const [sent, setSent] = useState("");

  useEffect(() => {
    const d = date || new Date().toISOString().slice(0, 10);
    api.card(workerId, d).then(setCard).catch((e) => setErr(e.message));
  }, [workerId, date]);

  const checkin = async (status) => {
    await api.checkin({ worker_id: card.worker_id, name: card.name, zone: card.zone_name, status, date: card.date });
    setSent(status === "unwell"
      ? "Your manager has been alerted and will call you. Move to the nearest cool point now."
      : "Thanks! Stay hydrated.");
  };

  if (err) return <div className="phone"><div className="error">{err}</div></div>;
  if (!card) return <div className="phone"><div className="loading">Loading…</div></div>;
  const b = BANDS[card.peak_band] || BANDS.SAFE;
  const r = card.nearest_rest;

  return (
    <div className="phone">
      <a className="back small" href="#/">← dashboard</a>
      <div className="wc-head">
        <div className="wc-name">{card.name}</div>
        <div className="muted">{card.zone_name} · {new Date(card.date + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}</div>
      </div>

      {card.stop_window && (
        <div className="wc-alert" style={{ background: BANDS.EXTREME.color }}>
          🔥 Extreme heat {card.stop_window}<br /><span>No outdoor work in this window.</span>
        </div>
      )}

      <div className="wc-block">
        <div className="wc-label">Your shift today</div>
        <div className="wc-big">{card.shift}</div>
        {card.changed && <div className="muted small">Changed from {card.original_shift} for heat safety</div>}
      </div>

      <div className="wc-block">
        <div className="wc-label">Breaks (paid) · in the shade, drink water</div>
        {card.breaks.length ? (
          <div className="chips">{card.breaks.map((x) => <span key={x} className="chip">{x}</span>)}</div>
        ) : <div className="muted">Short water breaks whenever you need</div>}
      </div>

      <div className="wc-block">
        <div className="wc-label">Nearest cool point</div>
        {r ? (
          <a className="wc-rest" target="_blank" rel="noreferrer"
            href={`https://www.openstreetmap.org/?mlat=${r.lat}&mlon=${r.lon}#map=17/${r.lat}/${r.lon}`}>
            💧 {r.name} · {r.distance_km} km →
          </a>
        ) : <div className="muted">Ask your hub for the nearest shaded spot</div>}
      </div>

      <div className="wc-row">
        <div className="wc-block half"><div className="wc-label">Drink</div><div className="wc-big">{card.water_l} L</div></div>
        <div className="wc-block half"><div className="wc-label">Your pay today</div><div className="wc-big">₹{card.guaranteed_pay_inr}</div><div className="muted small">guaranteed</div></div>
      </div>

      {card.new_joiner && <div className="wc-note">You're new: your body is still adjusting to the heat, so your limits are stricter for your first two weeks.</div>}

      <div className="wc-buttons">
        <button className="ok" onClick={() => checkin("ok")}>✅ I'm OK</button>
        <button className="unwell" onClick={() => checkin("unwell")}>🆘 I feel unwell</button>
      </div>
      {sent && <div className="wc-sent">{sent}</div>}
      <p className="muted small center">Reporting you feel unwell never affects your pay or rating.</p>
      <div className="muted small center" style={{ marginTop: 6 }}><span className="dot" style={{ background: b.color }} /> Peak today: {b.label}</div>
    </div>
  );
}
