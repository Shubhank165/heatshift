import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "./styles.css";
import Dashboard from "./Dashboard.jsx";
import WorkerCard from "./WorkerCard.jsx";

function useHash() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function App() {
  const hash = useHash();
  const m = hash.match(/^#\/worker\/(\w+)(?:\?date=([\d-]+))?/);
  if (m) return <WorkerCard workerId={m[1]} date={m[2]} />;
  return <Dashboard />;
}

createRoot(document.getElementById("root")).render(<App />);
