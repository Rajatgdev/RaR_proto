import { useEffect, useRef, useState, useCallback } from "react";
import * as api from "../lib/api";
import { GateCard, InfoCard, KV, Btn, Eyebrow } from "./ui";

const cvar = (v: string) => `var(--${v})`;

/* Guided conversation matching the demo spine. Everything - user messages,
   agent messages, and interactive cards - lives in one ordered `lines` array,
   so a new agent line always appears BELOW the card that triggered it. The
   agent narrates each step; irreversible steps are click-gated (agent-first,
   human-in-the-loop). On reopen, event_log replays as history and the correct
   live step is shown from job + board state. */

const fmtLocal = (iso: string, tz: string) =>
  new Date(iso).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit", timeZone: tz, timeZoneName: "short",
  });

function eventSentence(e: api.JobEvent): string | null {
  const d = e.detail ?? {};
  switch (e.action) {
    case "created_job": case "parsed_request": return "Job created from your request.";
    case "edited_card": return "Parameter card edited.";
    case "normalised_candidates": return typeof d.summary === "string" ? d.summary : "Candidates added.";
    case "confirmed_gate1": return "Gate 1 confirmed - calendar authorized.";
    case "generated_slots": return `Generated ${d.eligible ?? d.count ?? "some"} eligible times; offering up to 5.`;
    case "approved_gate2": return "Outreach approved (Gate 2).";
    case "sent_outreach": return `Sent ${d.count ?? ""} invitation${d.count === 1 ? "" : "s"}.`;
    case "reply_detected": return "A candidate replied - flagged for review.";
    case "sent_followup": return "Follow-up sent to a silent candidate.";
    case "parsed_reply": return `Parsed a reply${d.outcome ? ` -> ${d.outcome}` : ""}.`;
    case "confirmed_booking": return "Interview booked - event created, both parties emailed.";
    case "reoffer_sent": return `Re-offered ${d.offered ?? "new"} times near the candidate's preference.`;
    default: return null;
  }
}

/* A conversation line: text bubbles or an interactive card marker. Cards read
   live state from the parent via props, so they always reflect the backend. */
type Line =
  | { k: "agent"; text: string }
  | { k: "user"; text: string }
  | { k: "history"; text: string; ts: string }
  | { k: "card-gate1" }
  | { k: "card-intake" }
  | { k: "card-gate2" };

export function JobChat({
  jobId, newRequest, onBoardChanged,
}: {
  jobId: number; newRequest?: string; onBoardChanged?: () => void;
}) {
  const [job, setJob] = useState<api.JobDetail | null>(null);
  const [board, setBoard] = useState<api.Board | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const bootstrapped = useRef(false);

  const reload = useCallback(async () => {
    try { setJob(await api.getJob(jobId)); } catch { /* */ }
    try { setBoard(await api.getBoard(jobId)); } catch { /* */ }
  }, [jobId]);

  useEffect(() => { reload(); }, [reload]);

  // Bootstrap the transcript once, either as a fresh scripted conversation or
  // a replay of history for an existing job.
  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    if (newRequest !== undefined) {
      setLines([
        { k: "agent", text: "Hi - I'm the interview scheduling agent. I'll help you set up interviews with candidates. To start, tell me about the role: who's interviewing, how long, any hours to keep to, and the window to book within." },
        { k: "user", text: newRequest },
        { k: "agent", text: "Here's what I parsed, as a parameter card. Edit anything that's off and save, or confirm as-is." },
        { k: "card-gate1" },
      ]);
    } else {
      api.listEvents(jobId).then((events) => {
        const hist: Line[] = events
          .map((e): Line | null => { const s = eventSentence(e); return s ? { k: "history", text: s, ts: e.ts } : null; })
          .filter((l): l is Line => l !== null);
        setLines(hist.length ? hist : [{ k: "agent", text: "Reopened this job." }]);
        // append the correct live step
        api.getJob(jobId).then((jb) => api.getBoard(jobId).then((bd) => {
          setLines((p) => [...p, ...liveStep(jb, bd)]);
        }).catch(() => {})).catch(() => {});
      }).catch(() => {});
    }
    // eslint-disable-next-line
  }, [jobId, newRequest]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [lines.length]);

  const tz = job?.timezone ?? "UTC";
  const say = (text: string) => setLines((p) => [...p, { k: "agent", text }]);
  const addCard = (k: Line["k"]) => setLines((p) => [...p, { k } as Line]);

  function send() {
    const t = input.trim();
    if (!t) return;
    setInput("");
    setLines((p) => [...p, { k: "user", text: t }]);
    say("I act through the cards above - use the one that needs you next. (Free-text commands are coming soon.)");
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{ flex: 1, overflow: "auto", padding: "22px" }}>
        <div style={{ maxWidth: 600, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {lines.map((l, i) => {
            if (l.k === "user")
              return <div key={i} style={{ display: "flex", justifyContent: "flex-end" }}>
                <div style={{ maxWidth: "82%", background: cvar("accent"), color: "#fff", padding: "9px 13px", borderRadius: "14px 14px 4px 14px", fontSize: 13.5, lineHeight: 1.4 }}>{l.text}</div>
              </div>;
            if (l.k === "agent")
              return <div key={i} style={{ fontSize: 13.5, lineHeight: 1.55, maxWidth: "92%", color: cvar("ink") }}>{l.text}</div>;
            if (l.k === "history")
              return <div key={i} style={{ display: "flex", gap: 10, alignItems: "baseline", fontSize: 12.5, color: cvar("ink-muted") }}>
                <span aria-hidden style={{ color: cvar("hairline-2") }}>-</span>
                <span style={{ flex: 1 }}>{l.text}</span>
                <span className="mono" style={{ fontSize: 10.5, color: cvar("ink-subtle") }}>{new Date(l.ts).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
              </div>;
            if (l.k === "card-gate1" && job)
              return <Gate1Card key={i} job={job} board={board} say={say} addCard={addCard} reload={reload} onBoardChanged={onBoardChanged} />;
            if (l.k === "card-intake" && job)
              return <IntakeCard key={i} jobId={jobId} say={say} reload={reload} onBoardChanged={onBoardChanged} />;
            if (l.k === "card-gate2" && job)
              return <Gate2Card key={i} jobId={jobId} tz={tz} say={say} reload={reload} onBoardChanged={onBoardChanged} />;
            return null;
          })}

          {/* Running step (replies/booking) is derived, shown after outreach */}
          {job && board && isRunning(board) && (
            <RunningPanel jobId={jobId} tz={tz} board={board} say={say} reload={reload} onBoardChanged={onBoardChanged} />
          )}

          <div ref={endRef} />
        </div>
      </div>

      <div style={{ borderTop: cvar("hair"), background: cvar("paper"), padding: "12px 16px" }}>
        <div style={{ maxWidth: 600, margin: "0 auto", display: "flex", gap: 8, alignItems: "flex-end", border: cvar("hair"), borderRadius: cvar("radius-lg"), background: cvar("surface"), padding: 8 }}>
          <textarea value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            rows={1} placeholder="Message the agent..."
            style={{ flex: 1, resize: "none", border: "none", outline: "none", background: "transparent", fontSize: 13.5, padding: "6px 8px", maxHeight: 120 }} />
          <Btn small onClick={send} disabled={!input.trim()}>Send</Btn>
        </div>
      </div>
    </div>
  );
}

function isRunning(board: api.Board): boolean {
  return board.candidates.some((c) => ["confirmed", "reply_received", "needs_attention", "followup_sent", "slots_offered"].includes(c.status));
}

/* When reopening an existing job, append the card for wherever it's paused. */
function liveStep(job: api.JobDetail, board: api.Board): Line[] {
  if (job.status === "draft") return [{ k: "agent", text: "Continue setup below." }, { k: "card-gate1" }, { k: "card-intake" }];
  if (!isRunning(board)) return [{ k: "agent", text: "Gate 1 is confirmed. Review and send outreach below." }, { k: "card-gate2" }];
  return [{ k: "agent", text: "This job is running. Manage replies below or open the Board tab." }];
}

/* ---- Gate 1: editable parameter card ---- */
function Gate1Card({
  job, board, say, addCard, reload, onBoardChanged,
}: {
  job: api.JobDetail; board: api.Board | null;
  say: (t: string) => void; addCard: (k: Line["k"]) => void;
  reload: () => Promise<void>; onBoardChanged?: () => void;
}) {
  const [card, setCard] = useState<api.Card>(job.params);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [resolved, setResolved] = useState<string | null>(job.status !== "draft" ? "Confirmed - calendar authorized." : null);
  const [askedIntake, setAskedIntake] = useState(false);
  const nCandidates = board?.candidates.length ?? 0;

  useEffect(() => { setCard(job.params); }, [job.params]);

  // After the card is shown, ask for candidates once (script step).
  useEffect(() => {
    if (!askedIntake && job.status === "draft") {
      setAskedIntake(true);
      say("Now, add the candidates for this role - upload a CSV or type them manually below.");
      addCard("card-intake");
    }
    // eslint-disable-next-line
  }, []);

  async function saveEdit() {
    setPending(true);
    try {
      await api.updateCard(job.id, card);
      setEditing(false);
      await reload();
      say("Card updated. Edit again if needed, or confirm Gate 1 once candidates are added.");
    } catch (e) { say(`Couldn't save: ${(e as Error).message}`); }
    finally { setPending(false); }
  }

  async function confirmGate1() {
    if (nCandidates === 0) { say("Add at least one candidate before confirming Gate 1."); return; }
    setPending(true);
    try {
      await api.confirmJob(job.id);
      setResolved("Confirmed - calendar authorized.");
      say("Gate 1 confirmed and locked. To change anything now, edit the parameter card - that re-opens Gate 1. Reading the calendar and generating slots...");
      const g = await api.generateSlots(job.id);
      say(`${g.eligible} eligible times in the window -> offering ${g.offered} (max 5, spread for fairness). Here's the offer pool and the email preview - review, then send.`);
      addCard("card-gate2");
      await reload();
      onBoardChanged?.();
    } catch (e) { say(`Couldn't confirm: ${(e as Error).message}`); setResolved(null); }
    finally { setPending(false); }
  }

  const field = (label: string, key: keyof api.Card, kind: "text" | "num" = "text") => (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, fontSize: 12.5 }}>
      <span style={{ color: cvar("ink-muted") }}>{label}</span>
      <input value={String(card[key] as string | number)} className="tnum"
        onChange={(e) => setCard({ ...card, [key]: kind === "num" ? Number(e.target.value) : e.target.value })}
        style={{ border: cvar("hair"), borderRadius: cvar("radius"), padding: "5px 8px", fontSize: 12.5, background: cvar("paper"), width: 150, textAlign: "right" }} />
    </div>
  );

  return (
    <GateCard gate="Gate 1 - parameter card" title="Confirm the interview parameters"
      reassurance="No calendar is touched and nothing is sent until you confirm. At least one candidate is required first."
      primaryLabel="Confirm & read calendar" pending={pending} resolved={resolved}
      onPrimary={confirmGate1}
      onSecondary={editing ? saveEdit : () => setEditing(true)}
      secondaryLabel={editing ? "Save card" : "Edit"}>
      {editing ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {field("Role", "job_title")}
          {field("Duration (min)", "duration_min", "num")}
          {field("Window (days)", "window_days", "num")}
          {field("Work start", "work_start")}
          {field("Work end", "work_end")}
          {field("Buffer (min)", "buffer_min", "num")}
          {field("Max / interviewer / day", "max_per_interviewer_per_day", "num")}
        </div>
      ) : (
        <KV rows={[
          ["Role", card.job_title],
          ["Duration", `${card.duration_min} min`],
          ["Hours", `${card.work_start}-${card.work_end}`],
          ["Window", `${card.window_days} days`],
          ["Buffer", `${card.buffer_min} min`],
          ["Interviewer", card.interviewers?.[0]?.name ?? "-"],
        ]} />
      )}
      {!resolved && (
        <div style={{ fontSize: 12, color: nCandidates ? cvar("st-confirmed") : cvar("ink-subtle"), marginTop: 10 }}>
          {nCandidates ? `${nCandidates} candidate${nCandidates === 1 ? "" : "s"} ready` : "No candidates yet - add them in the next card."}
        </div>
      )}
    </GateCard>
  );
}

/* ---- Intake: CSV upload OR manual paste + normalisation ---- */
function IntakeCard({
  jobId, say, reload, onBoardChanged,
}: {
  jobId: number; say: (t: string) => void; reload: () => Promise<void>; onBoardChanged?: () => void;
}) {
  const [csv, setCsv] = useState("");
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => setCsv(String(reader.result ?? ""));
    reader.readAsText(f);
  }

  async function add() {
    if (!csv.trim()) return;
    setPending(true);
    try {
      const r = await api.intake(jobId, csv);
      await reload();
      onBoardChanged?.();
      const preview = r.ready.slice(0, 5).map((c) => `${c.name ?? c.email} (${c.email})`).join(", ");
      say(`Thanks - I normalised them. ${r.summary}.${r.ready.length ? ` Sample: ${preview}.` : ""}`);
      if (r.excluded.length === 0 && r.ready.length > 0) {
        say("If everything looks right, confirm Approval Gate 1 above. Once confirmed, you can generate the interview slots.");
        setDone(true);
      } else if (r.excluded.length) {
        say(`${r.excluded.length} row(s) need fixing - correct them and re-add.`);
      }
    } catch (e) { say(`Intake failed: ${(e as Error).message}`); }
    finally { setPending(false); }
  }

  return (
    <InfoCard>
      <Eyebrow>Candidates</Eyebrow>
      <div style={{ fontSize: 13, color: cvar("ink-muted"), marginBottom: 8 }}>
        Upload a CSV, or paste one per line as <span className="mono">name, email, timezone</span> (timezone optional - I default it and flag assumptions).
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <input ref={fileRef} type="file" accept=".csv,text/csv,text/plain" onChange={onFile} style={{ display: "none" }} />
        <Btn small variant="ghost" onClick={() => fileRef.current?.click()}>Upload CSV</Btn>
      </div>
      <textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={4}
        placeholder={"name,email,timezone\nMaya Chen, maya@example.com, Asia/Kolkata\nJon Reed, jon@example.com"}
        style={{ width: "100%", resize: "vertical", border: cvar("hair"), borderRadius: cvar("radius"), padding: 10, fontSize: 13, background: cvar("paper") }} />
      <div style={{ marginTop: 8 }}><Btn onClick={add} disabled={pending || !csv.trim()}>{pending ? "Adding..." : done ? "Re-add candidates" : "Add candidates"}</Btn></div>
    </InfoCard>
  );
}

/* ---- Gate 2: offer pool + editable email preview + send ---- */
function Gate2Card({
  jobId, tz, say, reload, onBoardChanged,
}: {
  jobId: number; tz: string; say: (t: string) => void; reload: () => Promise<void>; onBoardChanged?: () => void;
}) {
  const [slots, setSlots] = useState<api.SlotRow[]>([]);
  const [subject, setSubject] = useState("");
  const [bodyTxt, setBodyTxt] = useState("");
  const [preview, setPreview] = useState<api.Preview | null>(null);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [resolved, setResolved] = useState<string | null>(null);

  useEffect(() => {
    api.listSlots(jobId).then(setSlots).catch(() => {});
    api.getTemplate(jobId).then((t) => { setSubject(t.subject); setBodyTxt(t.body); }).catch(() => {});
  }, [jobId]);

  async function doPreview() {
    try { setPreview(await api.previewOutreach(jobId, subject, bodyTxt)); }
    catch (e) { say(`Preview failed: ${(e as Error).message}`); }
  }
  async function approveSend() {
    setPending(true);
    try {
      await api.approveOutreach(jobId, subject, bodyTxt);
      const r = await api.sendOutreach(jobId);
      setResolved(`Sent ${r.sent} invitation${r.sent === 1 ? "" : "s"}.`);
      say(`Sent ${r.sent} invitation${r.sent === 1 ? "" : "s"}. I'll follow up once if it goes quiet, and flag replies. Track everything in the Board tab.`);
      await reload();
      onBoardChanged?.();
    } catch (e) { say(`Send failed: ${(e as Error).message}`); }
    finally { setPending(false); }
  }

  const available = slots.filter((s) => s.status === "available" || s.status === "held");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <InfoCard>
        <Eyebrow>Offer pool - {available.length} slots</Eyebrow>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
          {available.map((s) => (
            <div key={s.slot_id} style={{ fontSize: 12.5, color: cvar("ink"), display: "flex", justifyContent: "space-between" }}>
              <span>{fmtLocal(s.start_ts, tz)}</span>
              <span style={{ color: cvar("ink-subtle") }}>available</span>
            </div>
          ))}
          {available.length === 0 && <div style={{ fontSize: 12.5, color: cvar("ink-muted") }}>No open slots.</div>}
        </div>
      </InfoCard>

      <GateCard gate="Gate 2 - outreach" title="Send interview invitations"
        reassurance="No emails have been sent. Preview or edit the message, then send to every candidate at once."
        primaryLabel="Approve & send invitations" pending={pending} resolved={resolved}
        onPrimary={approveSend}
        onSecondary={editing ? () => { setEditing(false); doPreview(); } : () => setEditing(true)}
        secondaryLabel={editing ? "Done editing" : preview ? "Edit email" : "Edit email"}
        onReject={preview ? undefined : doPreview} rejectLabel="Preview">
        {editing ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject"
              style={{ border: cvar("hair"), borderRadius: cvar("radius"), padding: "7px 9px", fontSize: 12.5, background: cvar("paper") }} />
            <textarea value={bodyTxt} onChange={(e) => setBodyTxt(e.target.value)} rows={8}
              style={{ border: cvar("hair"), borderRadius: cvar("radius"), padding: 10, fontSize: 12.5, background: cvar("paper"), resize: "vertical", lineHeight: 1.45 }} />
            <div style={{ fontSize: 11, color: cvar("ink-subtle") }}>Placeholders: {"{name} {interviewer} {job} {duration} {slots}"}</div>
          </div>
        ) : preview ? (
          <div style={{ border: cvar("hair"), borderRadius: cvar("radius"), padding: 12, background: cvar("paper"), fontSize: 12.5 }}>
            <div style={{ color: cvar("ink-subtle"), marginBottom: 6 }}>Preview - as {preview.to} would receive it:</div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{preview.subject}</div>
            <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.45 }}>{preview.body}</div>
          </div>
        ) : (
          <div style={{ fontSize: 12.5, color: cvar("ink-muted") }}>Each candidate is emailed in their own timezone. Use Preview to see the real email, or Edit to change it.</div>
        )}
      </GateCard>
    </div>
  );
}

/* ---- Running: reply review + book / re-offer ---- */
function RunningPanel({
  jobId, tz, board, say, reload, onBoardChanged,
}: {
  jobId: number; tz: string; board: api.Board;
  say: (t: string) => void; reload: () => Promise<void>; onBoardChanged?: () => void;
}) {
  const [active, setActive] = useState<number | null>(null);
  const [res, setRes] = useState<api.ReplyParse | null>(null);
  const [slot, setSlot] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  const [reoffering, setReoffering] = useState(false);

  const needReview = board.candidates.filter((c) => ["reply_received", "slots_offered", "followup_sent"].includes(c.status));

  async function read(cid: number) {
    setActive(cid); setRes(null); setSlot(null); setPending(true);
    try {
      const r = await api.parseReply(jobId, cid);
      setRes(r);
      if (r.status === "confirm" && r.proposed_slots?.length) setSlot(r.proposed_slots[0].slot_id);
      if (r.status === "no_reply") say("No candidate reply in that thread yet.");
      if (r.status === "escalate") say("That reply proposed a different time - you can re-offer the closest available slots below.");
    } catch (e) { say(`Couldn't read reply: ${(e as Error).message}`); }
    finally { setPending(false); }
  }
  async function book() {
    if (active == null || slot == null) return;
    setPending(true);
    try {
      const b = await api.confirmBooking(jobId, active, slot);
      say(`Booked. Event created and both parties emailed - ${b.when}.`);
      setRes(null); setActive(null);
      await reload(); onBoardChanged?.();
    } catch (e) { say(`Booking failed: ${(e as Error).message}`); }
    finally { setPending(false); }
  }
  async function doReoffer(cid: number) {
    setReoffering(true);
    try {
      const r = await api.reoffer(jobId, cid);
      say(`Re-offered ${r.slots_offered} times near ${r.target_time}. Watching for their reply.`);
      setRes(null); setActive(null);
      await reload(); onBoardChanged?.();
    } catch (e) { say(`Re-offer failed: ${(e as Error).message}`); }
    finally { setReoffering(false); }
  }

  return (
    <>
      <InfoCard>
        <Eyebrow>Candidates in flight</Eyebrow>
        {needReview.length === 0 ? (
          <div style={{ fontSize: 13, color: cvar("ink-muted") }}>Everyone's booked or nothing needs you. See the Board tab for the full picture.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
            {needReview.map((c) => (
              <div key={c.candidate_id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name ?? c.email}</div>
                  <div style={{ fontSize: 11.5, color: c.status === "reply_received" ? cvar("st-review") : cvar("ink-subtle") }}>
                    {c.status === "reply_received" ? "replied - review" : c.status.replace("_", " ")}
                  </div>
                </div>
                <Btn small variant="ghost" onClick={() => read(c.candidate_id)} disabled={pending}>Read reply</Btn>
              </div>
            ))}
          </div>
        )}
      </InfoCard>

      {res?.status === "confirm" && active != null && (
        <GateCard gate="Confirm booking" title="Book the slot the candidate chose"
          reassurance="No event is created until you confirm. This creates a calendar event and emails both parties."
          primaryLabel="Create event & notify both" pending={pending} onPrimary={book}>
          {res.reply_body && (
            <div style={{ fontSize: 12.5, color: cvar("ink-muted"), marginBottom: 10, whiteSpace: "pre-wrap", borderLeft: `2px solid ${cvar("hairline-2")}`, paddingLeft: 10 }}>
              {res.reply_body.slice(0, 220)}
            </div>
          )}
          <div style={{ fontSize: 12.5, marginBottom: 8, color: cvar("ink-muted") }}>
            Confidence {typeof res.confidence === "number" ? res.confidence.toFixed(2) : "-"} - pick the slot:
          </div>
          <select value={slot ?? undefined} onChange={(e) => setSlot(Number(e.target.value))}
            style={{ width: "100%", border: cvar("hair"), borderRadius: cvar("radius"), padding: "8px 10px", fontSize: 13, background: cvar("paper") }}>
            {(res.proposed_slots ?? []).map((s) => (
              <option key={s.slot_id} value={s.slot_id}>{fmtLocal(s.start, tz)}</option>
            ))}
          </select>
        </GateCard>
      )}

      {res?.status === "escalate" && active != null && (
        <GateCard gate="Re-offer - review required" title="Propose the closest available times"
          reassurance="Draft - nothing sent yet. I'll email up to 5 valid times nearest their request, within the job's hours."
          primaryLabel="Approve & send re-offer" pending={reoffering} onPrimary={() => doReoffer(active)}>
          <div style={{ fontSize: 12.5, color: cvar("ink-muted") }}>
            {res.note ?? res.reason ?? "The candidate asked for a time outside what was offered."}
          </div>
        </GateCard>
      )}
    </>
  );
}