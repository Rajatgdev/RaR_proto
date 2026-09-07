import { useEffect, useState } from "react";
import { getAvailability, getStatus, loginUrl, type Availability, type Status } from "./lib/api";

// Phase 1: connect a real Google account, read FreeBusy, render computed slots.
export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [avail, setAvail] = useState<Availability | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getStatus().then(setStatus).catch((e) => setError(String(e)));
  }, []);

  async function loadSlots() {
    setError(null);
    setLoading(true);
    try {
      setAvail(await getAvailability());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const byDay = groupByDay(avail?.slots ?? []);

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 720, margin: "3rem auto", padding: "0 1rem" }}>
      <h1>Scheduling Agent — Phase 1</h1>
      <p>Connect a Google account, then read real free/busy and compute slots.</p>

      {!status?.connected ? (
        <a href={loginUrl()}>
          <button style={btn}>Connect Google Calendar</button>
        </a>
      ) : (
        <>
          <p>
            Connected as <strong>{status.email}</strong>{" "}
            <a href={loginUrl()} style={{ fontSize: 13 }}>(reconnect)</a>
          </p>
          <button style={btn} onClick={loadSlots} disabled={loading}>
            {loading ? "Loading…" : "Load availability"}
          </button>
        </>
      )}

      {error && <pre style={{ color: "crimson", whiteSpace: "pre-wrap" }}>{error}</pre>}

      {avail && (
        <>
          <p style={{ marginTop: 24 }}>
            <strong>{avail.count}</strong> slots for {avail.calendar}
          </p>
          {Object.entries(byDay).map(([day, slots]) => (
            <div key={day} style={{ marginBottom: 16 }}>
              <h3 style={{ margin: "8px 0" }}>{day}</h3>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {slots.map((s) => (
                  <span key={s.start} style={chip}>{fmtTime(s.start)}</span>
                ))}
              </div>
            </div>
          ))}
        </>
      )}
    </main>
  );
}

const btn: React.CSSProperties = { padding: "10px 18px", fontSize: 15, cursor: "pointer" };
const chip: React.CSSProperties = { padding: "6px 10px", background: "#eef", borderRadius: 6, fontSize: 14 };

function groupByDay(slots: { start: string; end: string }[]) {
  const out: Record<string, { start: string; end: string }[]> = {};
  for (const s of slots) {
    const day = new Date(s.start).toLocaleDateString(undefined, {
      weekday: "short", day: "numeric", month: "short",
    });
    (out[day] ??= []).push(s);
  }
  return out;
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}