import { useEffect, useState } from "react";
import {
  confirmJob, createJob, getAvailability, getStatus, intake, loginUrl, updateCard,
  type Availability, type Card, type Job, type NormResult, type Status,
} from "./lib/api";

const TZ = "Europe/London";

// Phase 2: parameter card -> intake -> normalise -> Gate 1.
// Gate rules: fields lock on confirm; editing re-opens the gate; confirm is
// blocked while any candidate row is faulty. Availability sits behind the gate.
export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const [request, setRequest] = useState(
    "30-minute Google Meet screens with Jamie over the next two weeks, mornings only, 10-minute gaps"
  );
  const [job, setJob] = useState<Job | null>(null);
  const [card, setCard] = useState<Card | null>(null);
  const [csv, setCsv] = useState("name,email\nAlex Candidate,alex@example.com\n");
  const [normResult, setNormResult] = useState<NormResult | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [avail, setAvail] = useState<Availability | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getStatus().then(setStatus).catch((e) => setError(String(e)));
  }, []);

  // auto-dismiss the saved/updated toast
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2500);
    return () => clearTimeout(t);
  }, [toast]);

  const run = async (fn: () => Promise<void>) => {
    setError(null); setBusy(true);
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  // Derived gate conditions.
  const hasCandidates = (normResult?.ready.length ?? 0) > 0;
  const hasFaulty = (normResult?.excluded.length ?? 0) > 0;
  const canConfirm = !!card && hasCandidates && !hasFaulty && !confirmed;

  const parse = () => run(async () => {
    const j = await createJob(request, TZ);
    setJob(j); setCard(j.card);
    setConfirmed(false); setAvail(null); setNormResult(null);
  });

  const saveCard = () => run(async () => {
    if (!job || !card) return;
    const r = await updateCard(job.job_id, card);
    if (r.status === "draft" && confirmed) setConfirmed(false);  // re-open gate
    setAvail(null);
    setToast("Parameter card saved");
  });

  const loadIntake = () => run(async () => {
    if (!job) return;
    const r = await intake(job.job_id, csv);
    setNormResult(r);
    setToast(r.summary);
    // a fresh intake that (re)introduces faults must re-open the gate
    if (r.excluded.length > 0 && confirmed) { setConfirmed(false); setAvail(null); }
  });

  const doConfirm = () => run(async () => {
    if (!job || !card) return;
    await updateCard(job.job_id, card);   // persist any last edits (keeps it draft)
    await confirmJob(job.job_id);          // server re-checks candidates + faults
    setConfirmed(true);
    setToast("Confirmed — calendar reads unlocked");
  });

  const editAgain = () => { setConfirmed(false); setAvail(null); setToast("Editing re-opened — confirm again when ready"); };

  const loadAvail = () => run(async () => {
    if (!job) return; setAvail(await getAvailability(job.job_id));
  });

  const set = <K extends keyof Card>(k: K, v: Card[K]) =>
    setCard((c) => (c ? { ...c, [k]: v } : c));

  const locked = confirmed;  // fields are read-only once confirmed

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 760, margin: "3rem auto", padding: "0 1rem" }}>
      <h1>Scheduling Agent — Phase 2</h1>

      {!status?.connected ? (
        <a href={loginUrl()}><button style={btn}>Connect Google Calendar</button></a>
      ) : (
        <p>Connected as <strong>{status.email}</strong> <a href={loginUrl()} style={sm}>(reconnect)</a></p>
      )}

      <section style={box}>
        <h3>1 · Describe the interviews</h3>
        <textarea value={request} onChange={(e) => setRequest(e.target.value)}
          rows={3} style={{ width: "100%", padding: 8, fontFamily: "inherit" }} />
        <button style={btn} onClick={parse} disabled={busy}>Parse into parameter card</button>
      </section>

      {card && (
        <section style={box}>
          <h3>2 · Parameter card <span style={sm}>{locked ? "(locked — confirmed)" : "(edit any field)"}</span></h3>
          {card.note && <p style={sm}>Agent: {card.note}</p>}
          <div style={grid}>
            <Field label="Job title"><input style={inp} value={card.job_title} disabled={locked}
              onChange={(e) => set("job_title", e.target.value)} /></Field>
            <Field label="Duration (min)"><select style={inp} value={card.duration_min} disabled={locked}
              onChange={(e) => set("duration_min", Number(e.target.value))}>
              {[30, 45, 60].map((d) => <option key={d} value={d}>{d}</option>)}</select></Field>
            <Field label="Window (working days)"><input style={inp} type="number" value={card.window_days} disabled={locked}
              onChange={(e) => set("window_days", Number(e.target.value))} /></Field>
            <Field label="Buffer (min)"><input style={inp} type="number" value={card.buffer_min} disabled={locked}
              onChange={(e) => set("buffer_min", Number(e.target.value))} /></Field>
            <Field label="Work start"><input style={inp} value={card.work_start} disabled={locked}
              onChange={(e) => set("work_start", e.target.value)} /></Field>
            <Field label="Work end"><input style={inp} value={card.work_end} disabled={locked}
              onChange={(e) => set("work_end", e.target.value)} /></Field>
            <Field label="Max / interviewer / day"><input style={inp} type="number"
              value={card.max_per_interviewer_per_day} disabled={locked}
              onChange={(e) => set("max_per_interviewer_per_day", Number(e.target.value))} /></Field>
          </div>
          <p style={sm}>Interviewers: {card.interviewers.map((i) => i.name).join(", ") || "—"}</p>
          {!locked
            ? <button style={btnGhost} onClick={saveCard} disabled={busy}>Save edits</button>
            : <button style={btnGhost} onClick={editAgain} disabled={busy}>Edit (re-opens Gate 1)</button>}
        </section>
      )}

      {job && (
        <section style={box}>
          <h3>3 · Candidates <span style={sm}>(upload a CSV or type below: name,email[,phone,timezone])</span></h3>
          <input type="file" accept=".csv,text/csv" disabled={locked}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              const reader = new FileReader();
              reader.onload = () => { setCsv(String(reader.result ?? "")); setToast(`Loaded ${f.name}`); };
              reader.onerror = () => setError(`could not read ${f.name}`);
              reader.readAsText(f);
              e.target.value = "";  // allow re-selecting the same file
            }}
            style={{ marginBottom: 8, display: "block" }} />
          <textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={4}
            disabled={locked}
            style={{ width: "100%", padding: 8, fontFamily: "monospace" }} />
          <button style={btn} onClick={loadIntake} disabled={busy || locked}>Normalise candidates</button>
          {normResult && (
            <div style={{ marginTop: 10 }}>
              <strong>{normResult.summary}</strong>
              <ul>
                {normResult.ready.map((c) => (
                  <li key={c.email}>{c.name ?? "(no name)"} · {c.email}
                    {" "}<em style={sm}>· {c.timezone}{c.timezone_assumed ? " (assumed)" : ""}</em></li>
                ))}
                {normResult.excluded.map((c, i) => (
                  <li key={i} style={{ color: "#a00" }}>{c.email ?? "(no email)"} — {c.reason}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {job && (
        <section style={{ ...box, borderColor: confirmed ? "#3a3" : "#e5a300" }}>
          <h3>4 · Approval Gate 1 <span style={sm}>— nothing touches a calendar until you confirm</span></h3>
          {!confirmed ? (
            <>
              <button style={btn} onClick={doConfirm} disabled={busy || !canConfirm}>
                Confirm parameter card
              </button>
              {!hasCandidates && <p style={sm}>Add candidates and run Normalise first.</p>}
              {hasFaulty && <p style={{ ...sm, color: "#a00" }}>
                Fix the flagged candidate row(s) and re-run Normalise before you can confirm.
              </p>}
            </>
          ) : (
            <>
              <p style={{ color: "#3a3" }}>✓ Confirmed. Calendar reads are now unlocked.</p>
              <button style={btn} onClick={loadAvail} disabled={busy}>Load availability</button>
            </>
          )}
        </section>
      )}

      {error && <pre style={{ color: "crimson", whiteSpace: "pre-wrap" }}>{error}</pre>}

      {avail && (
        <section style={box}>
          <h3>{avail.count} slots for {avail.calendar}</h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {avail.slots.slice(0, 40).map((s) => (
              <span key={s.start} style={chip}>{fmt(s.start)}</span>
            ))}
          </div>
          {avail.slots.length > 40 && <p style={sm}>…and {avail.slots.length - 40} more</p>}
        </section>
      )}

      {toast && <div style={toastStyle}>{toast}</div>}
    </main>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label style={{ display: "flex", flexDirection: "column", fontSize: 13, gap: 4 }}>
    {label}{children}</label>;
}
function fmt(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

const box: React.CSSProperties = { border: "1px solid #ddd", borderRadius: 8, padding: 16, marginTop: 16 };
const grid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 10 };
const btn: React.CSSProperties = { padding: "9px 16px", fontSize: 14, cursor: "pointer", marginTop: 10 };
const btnGhost: React.CSSProperties = { ...btn, background: "#f3f3f3" };
const inp: React.CSSProperties = { padding: 6, fontSize: 14 };
const chip: React.CSSProperties = { padding: "5px 9px", background: "#eef", borderRadius: 6, fontSize: 13 };
const sm: React.CSSProperties = { fontSize: 12, color: "#666" };
const toastStyle: React.CSSProperties = {
  position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
  background: "#222", color: "#fff", padding: "10px 18px", borderRadius: 8, fontSize: 14,
  boxShadow: "0 4px 14px rgba(0,0,0,.25)",
};