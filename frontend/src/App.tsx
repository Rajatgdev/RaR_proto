import { useEffect, useState } from "react";

import {
  approveOutreach, bookSlot, confirmJob, createJob, generateSlots, getStatus, getTemplate,
  holdSlot, intake, listSlots, loginUrl, parseReply, previewOutreach, sendOutreach, updateCard,
  type Card, type GenResult, type Job, type NormResult, type SendResult, type SlotRow,
  type Preview, type ReplyParse, type Status, type Template,
} from "./lib/api";

const TZ = "Europe/London";

// Phase 4b: after outreach is sent, read the candidate's reply, run one LLM
// parse -> availability window + confidence, intersect against held slots, then
// propose (high confidence) or escalate to Needs attention (low). Never books.
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
  const [gen, setGen] = useState<GenResult | null>(null);
  const [slots, setSlots] = useState<SlotRow[]>([]);
  const [holds, setHolds] = useState<Record<number, string>>({});
  const [firstCandidateId, setFirstCandidateId] = useState<number | null>(null);
  const [tpl, setTpl] = useState<Template | null>(null);
  const [sent, setSent] = useState<SendResult | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [replyParse, setReplyParse] = useState<ReplyParse | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getStatus().then(setStatus).catch((e) => setError(String(e)));
  }, []);

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

  const hasCandidates = (normResult?.ready.length ?? 0) > 0;
  const hasFaulty = (normResult?.excluded.length ?? 0) > 0;
  const canConfirm = !!card && hasCandidates && !hasFaulty && !confirmed;

  const parse = () => run(async () => {
    const j = await createJob(request, TZ);
    setJob(j); setCard(j.card);
    setConfirmed(false); setNormResult(null); setGen(null); setSlots([]); setHolds({}); setTpl(null); setSent(null); setPreview(null); setReplyParse(null);
  });

  const saveCard = () => run(async () => {
    if (!job || !card) return;
    const r = await updateCard(job.job_id, card);
    if (r.status === "draft" && confirmed) setConfirmed(false);  // re-open gate
    setGen(null); setSlots([]); setHolds({}); setTpl(null); setSent(null); setPreview(null); setReplyParse(null);
    setToast("Parameter card saved");
  });

  const loadIntake = () => run(async () => {
    if (!job) return;
    const r = await intake(job.job_id, csv);
    setNormResult(r);
    setToast(r.summary);
    if (r.excluded.length > 0 && confirmed) { setConfirmed(false); setGen(null); setSlots([]); }
  });

  const doConfirm = () => run(async () => {
    if (!job || !card) return;
    await updateCard(job.job_id, card);   // persist any last edits (keeps it draft)
    await confirmJob(job.job_id);          // server re-checks candidates + faults
    setConfirmed(true);
    setToast("Confirmed — slot generation unlocked");
  });

  const editAgain = () => { setConfirmed(false); setGen(null); setSlots([]); setHolds({}); setTpl(null); setSent(null); setPreview(null); setReplyParse(null); setToast("Editing re-opened — confirm again when ready"); };

  const refreshSlots = async (jobId: number) => setSlots(await listSlots(jobId));

  const genSlots = () => run(async () => {
    if (!job) return;
    const g = await generateSlots(job.job_id);
    setGen(g); await refreshSlots(job.job_id);
    const res = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ""}/jobs/${job.job_id}`).then((r) => r.json());
    setFirstCandidateId(res.candidates?.[0]?.id ?? null);
    setTpl(await getTemplate(job.job_id));   // load outreach template for Gate 2
    setSent(null);
    setToast(`Offered ${g.offered} of ${g.eligible} eligible`);
  });

  const doPreview = () => run(async () => {
    if (!job || !tpl) return;
    setPreview(await previewOutreach(job.job_id, tpl.subject, tpl.body));
  });

  const approve = () => run(async () => {
    if (!job || !tpl) return;
    const r = await approveOutreach(job.job_id, tpl.subject, tpl.body);
    setTpl({ ...tpl, approved: true });
    setToast(`Gate 2 approved — pool of ${r.pool_size}`);
  });

  const doSend = () => run(async () => {
    if (!job) return;
    const r = await sendOutreach(job.job_id);
    setSent(r);
    await refreshSlots(job.job_id);
    setToast(`Sent ${r.sent} outreach email(s)`);
  });

  const doParseReply = () => run(async () => {
    if (!job || !firstCandidateId) throw new Error("no candidate to read a reply for");
    const r = await parseReply(job.job_id, firstCandidateId);
    setReplyParse(r);
    setToast(r.status === "confirm" ? "High-confidence match — review & confirm"
      : r.status === "escalate" ? "Escalated to Needs attention"
      : "No reply yet");
  });

  const hold = (slotId: number) => run(async () => {
    if (!job || !firstCandidateId) throw new Error("no candidate to hold with");
    const h = await holdSlot(job.job_id, slotId, firstCandidateId);
    setHolds((m) => ({ ...m, [slotId]: h.hold_id }));
    await refreshSlots(job.job_id);
    setToast("Slot held");
  });

  const bookIt = (slotId: number) => run(async () => {
    if (!job || !firstCandidateId) return;
    await bookSlot(job.job_id, slotId, firstCandidateId, holds[slotId]);
    await refreshSlots(job.job_id);
    setToast("Slot booked");
  });

  const set = <K extends keyof Card>(k: K, v: Card[K]) =>
    setCard((c) => (c ? { ...c, [k]: v } : c));

  const locked = confirmed;

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 760, margin: "3rem auto", padding: "0 1rem" }}>
      <h1>Scheduling Agent — Phase 4</h1>

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
              e.target.value = "";
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
              <p style={{ color: "#3a3" }}>✓ Confirmed. Slot generation unlocked.</p>
              <button style={btn} onClick={genSlots} disabled={busy}>Generate offer slots</button>
              {gen && <p style={sm}>{gen.eligible} eligible in window → offered {gen.offered} (max 5, spread for fairness)</p>}
            </>
          )}
        </section>
      )}

      {slots.length > 0 && (
        <section style={box}>
          <h3>5 · Offer pool <span style={sm}>(hold → book; the double-booking guard is server-side)</span></h3>
          <ul style={{ listStyle: "none", padding: 0 }}>
            {slots.map((s) => (
              <li key={s.slot_id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 0" }}>
                <span style={{ minWidth: 190 }}>{fmtFull(s.start_ts)}</span>
                <span style={{ ...chip, background: s.status === "booked" ? "#dfd" : s.status === "held" ? "#ffe8bf" : "#eef" }}>
                  {s.status}
                </span>
                {s.status === "available" && (
                  <button style={btnSm} onClick={() => hold(s.slot_id)} disabled={busy}>Hold</button>
                )}
                {s.status === "held" && holds[s.slot_id] && (
                  <button style={btnSm} onClick={() => bookIt(s.slot_id)} disabled={busy}>Book</button>
                )}
              </li>
            ))}
          </ul>
          <p style={sm}>Candidate used for this manual test: id {firstCandidateId ?? "—"}</p>
        </section>
      )}

      {tpl && (
        <section style={{ ...box, borderColor: tpl.approved ? "#3a3" : "#e5a300" }}>
          <h3>6 · Outreach &amp; Approval Gate 2 <span style={sm}>— approve the message + pool once, then send</span></h3>
          <Field label="Subject">
            <input style={inp} value={tpl.subject} disabled={tpl.approved}
              onChange={(e) => setTpl({ ...tpl, subject: e.target.value })} />
          </Field>
          <label style={{ display: "flex", flexDirection: "column", fontSize: 13, gap: 4, marginTop: 8 }}>
            Body <span style={sm}>placeholders: {"{name} {interviewer} {job} {duration} {slots}"}</span>
            <textarea rows={9} value={tpl.body} disabled={tpl.approved}
              onChange={(e) => setTpl({ ...tpl, body: e.target.value })}
              style={{ padding: 8, fontFamily: "inherit" }} />
          </label>

          <button style={btnGhost} onClick={doPreview} disabled={busy}>Preview candidate email</button>
          {preview && (
            <div style={{ border: "1px solid #ccd", borderRadius: 8, padding: 12, marginTop: 10, background: "#fafbff" }}>
              <p style={sm}>Preview — as <strong>{preview.to}</strong> would receive it:</p>
              <p style={{ margin: "4px 0", fontWeight: 600 }}>{preview.subject}</p>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>{preview.body}</pre>
            </div>
          )}

          {!tpl.approved ? (
            <button style={btn} onClick={approve} disabled={busy}>Approve outreach (Gate 2)</button>
          ) : !sent ? (
            <>
              <p style={{ color: "#3a3" }}>✓ Approved. Ready to send real emails via the connected mailbox.</p>
              <button style={btn} onClick={doSend} disabled={busy}>Send outreach emails</button>
            </>
          ) : (
            <div>
              <p style={{ color: "#3a3" }}>✓ Sent {sent.sent} email(s). Candidates moved to "slots offered"; slots held.</p>
              <ul style={sm as React.CSSProperties}>
                {sent.candidates.map((c) => (
                  <li key={c.candidate_id}>{c.email} — thread {c.thread_id.slice(0, 10)}… · {c.held} slots held</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {sent && (
        <section style={box}>
          <h3>7 · Candidate reply <span style={sm}>(read the reply, parse it, propose or escalate)</span></h3>
          <p style={sm}>Reads the latest reply for candidate id {firstCandidateId ?? "—"} and runs one LLM parse.</p>
          <button style={btn} onClick={doParseReply} disabled={busy}>Read &amp; parse reply</button>

          {replyParse && replyParse.status === "no_reply" && (
            <p style={sm}>{replyParse.message}</p>
          )}

          {replyParse && replyParse.reply_body && (
            <div style={{ marginTop: 12 }}>
              <p style={sm}>Reply from {replyParse.reply_from}:</p>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", background: "#f6f6f6", padding: 10, borderRadius: 6, margin: "4px 0" }}>{replyParse.reply_body}</pre>
              <p style={sm}>
                Confidence <strong>{(replyParse.confidence ?? 0).toFixed(2)}</strong>
                {" · "}availability answer: {String(replyParse.is_availability_answer)}
                {replyParse.note ? ` · ${replyParse.note}` : ""}
              </p>

              {replyParse.status === "confirm" ? (
                <div style={{ border: "1px solid #3a3", borderRadius: 8, padding: 12, marginTop: 8, background: "#f3fff3" }}>
                  <p style={{ margin: "0 0 6px", fontWeight: 600 }}>Proposed — recruiter confirms (booking is Phase 4c):</p>
                  <ul style={{ margin: 0 }}>
                    {replyParse.proposed_slots?.map((s) => (
                      <li key={s.slot_id}>{fmtFull(s.start)} <span style={sm}>(slot {s.slot_id})</span></li>
                    ))}
                  </ul>
                  <p style={sm}>[Confirm] / [Edit] wired in 4c — this proves parse → match → propose, no auto-book.</p>
                </div>
              ) : (
                <div style={{ border: "1px solid #e5a300", borderRadius: 8, padding: 12, marginTop: 8, background: "#fffaf0" }}>
                  <p style={{ margin: 0 }}>⚠ Escalated to <strong>Needs attention</strong> — {replyParse.reason}. Recruiter handles manually.</p>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {error && <pre style={{ color: "crimson", whiteSpace: "pre-wrap" }}>{error}</pre>}

      {toast && <div style={toastStyle}>{toast}</div>}
    </main>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label style={{ display: "flex", flexDirection: "column", fontSize: 13, gap: 4 }}>
    {label}{children}</label>;
}
function fmtFull(iso: string) {
  return new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

const box: React.CSSProperties = { border: "1px solid #ddd", borderRadius: 8, padding: 16, marginTop: 16 };
const grid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 10 };
const btn: React.CSSProperties = { padding: "9px 16px", fontSize: 14, cursor: "pointer", marginTop: 10 };
const btnSm: React.CSSProperties = { padding: "4px 10px", fontSize: 13, cursor: "pointer" };
const btnGhost: React.CSSProperties = { ...btn, background: "#f3f3f3" };
const inp: React.CSSProperties = { padding: 6, fontSize: 14 };
const chip: React.CSSProperties = { padding: "5px 9px", background: "#eef", borderRadius: 6, fontSize: 13 };
const sm: React.CSSProperties = { fontSize: 12, color: "#666" };
const toastStyle: React.CSSProperties = {
  position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
  background: "#222", color: "#fff", padding: "10px 18px", borderRadius: 8, fontSize: 14,
  boxShadow: "0 4px 14px rgba(0,0,0,.25)",
};