import { useEffect, useRef, useState, useCallback } from "react";
import * as api from "../lib/api";
import { GateCard, InfoCard, KV, Btn, Eyebrow } from "./ui";

const cvar = (v: string) => `var(--${v})`;

/* The job-chat drives the demo spine as a conversation, per the spec order:
   request -> EDITABLE parameter card -> candidate intake + normalise -> Gate 1
   (confirm, needs >=1 candidate) -> generate slots (offer pool) -> Gate 2
   (approve + send) -> candidate replies -> confirm-book / re-offer. Agent-first:
   the agent narrates and surfaces click-cards; irreversible steps are gated.
   Phase is derived from live job + board so reopening resumes correctly. */

type Line =
  | { k: "agent"; text: string }
  | { k: "user"; text: string }
  | { k: "history"; text: string; ts: string };

const fmtLocal = (iso: string, tz: string) =>
  new Date(iso).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit", timeZone: tz, timeZoneName: "short",
  });

function eventSentence(e: api.JobEvent): string | null {
  const d = e.detail ?? {};
  switch (e.action) {
    case "created_job": return "Job created from your request.";
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

type Phase = "card" | "outreach" | "running";

export function JobChat({
  jobId, isNew, onBoardChanged,
}: {
  jobId: number; isNew?: boolean; onBoardChanged?: () => void;
}) {
  const [job, setJob] = useState<api.JobDetail | null>(null);
  const [board, setBoard] = useState<api.Board | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  const reloadJob = useCallback(async () => {
    try { setJob(await api.getJob(jobId)); } catch { /* */ }
    try { setBoard(await api.getBoard(jobId)); } catch { /* */ }
  }, [jobId]);

  useEffect(() => { reloadJob(); }, [reloadJob]);

  useEffect(() => {
    if (isNew) {
      setLines([{ k: "agent", text: "Here's the parameter card I parsed from your request. Edit anything that's off, add candidates, then confirm - nothing touches a calendar until you do." }]);
      return;
    }
    let alive = true;
    api.listEvents(jobId).then((events) => {
      if (!alive) return;
      const hist: Line[] = events
        .map((e): Line | null => { const s = eventSentence(e); return s ? { k: "history", text: s, ts: e.ts } : null; })
        .filter((l): l is Line => l !== null);
      setLines(hist.length ? hist : [{ k: "agent", text: "Reopened this job. Continue where you left off using the cards below." }]);
    }).catch(() => {});
    return () => { alive = false; };
  }, [jobId, isNew]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [lines.length, job?.status, board?.candidates.length]);

  const tz = job?.timezone ?? "UTC";
  const say = (text: string) => setLines((p) => [...p, { k: "agent", text }]);

  function send() {
    const t = input.trim();
    if (!t) return;
    setInput("");
    setLines((p) => [...p, { k: "user", text: t }]);
    say("Noted - I act through the cards below, not from chat text. Use the card that needs you next.");
  }

  const candidates = board?.candidates ?? [];
  const phase: Phase =
    !job ? "card"
    : job.status === "draft" ? "card"
    : candidates.some((c) => ["confirmed", "reply_received", "needs_attention", "followup_sent", "slots_offered"].includes(c.status)) ? "running"
    : "outreach";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{ flex: 1, overflow: "auto", padding: "22px" }}>
        <div style={{ maxWidth: 600, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {lines.map((l, i) =>
            l.k === "user" ? (
              <div key={i} style={{ display: "flex", justifyContent: "flex-end" }}>
                <div style={{ maxWidth: "82%", background: cvar("accent"), color: "#fff", padding: "9px 13px", borderRadius: "14px 14px 4px 14px", fontSize: 13.5, lineHeight: 1.4 }}>{l.text}</div>
              </div>
            ) : l.k === "history" ? (
              <div key={i} style={{ display: "flex", gap: 10, alignItems: "baseline", fontSize: 12.5, color: cvar("ink-muted") }}>
                <span aria-hidden style={{ color: cvar("hairline-2") }}>-</span>
                <span style={{ flex: 1 }}>{l.text}</span>
                <span className="mono" style={{ fontSize: 10.5, color: cvar("ink-subtle") }}>
                  {new Date(l.ts).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                </span>
              </div>
            ) : (
              <div key={i} style={{ fontSize: 13.5, lineHeight: 1.55, maxWidth: "92%", color: cvar("ink") }}>{l.text}</div>
            ),
          )}

          {job && phase === "card" && (
            <CardAndIntake job={job} board={board} tz={tz} say={say} reload={reloadJob} onBoardChanged={onBoardChanged} />
          )}
          {job && phase === "outreach" && (
            <OutreachGate jobId={jobId} say={say} reload={reloadJob} onBoardChanged={onBoardChanged} />
          )}
          {job && phase === "running" && (
            <RunningPanel jobId={jobId} tz={tz} board={board} say={say} reload={reloadJob} onBoardChanged={onBoardChanged} />
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

function CardAndIntake({
  job, board, tz, say, reload, onBoardChanged,
}: {
  job: api.JobDetail; board: api.Board | null; tz: string;
  say: (t: string) => void; reload: () => Promise<void>; onBoardChanged?: () => void;
}) {
  const [card, setCard] = useState<api.Card>(job.params);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [csv, setCsv] = useState("");
  const [normSummary, setNormSummary] = useState<string | null>(null);
  const nCandidates = board?.candidates.length ?? 0;
  void tz;

  useEffect(() => { setCard(job.params); }, [job.params]);

  async function saveEdit() {
    setPending(true);
    try {
      await api.updateCard(job.id, card);
      setEditing(false);
      say("Card updated. Add candidates, then confirm Gate 1.");
      await reload();
    } catch (e) { say(`Couldn't save: ${(e as Error).message}`); }
    finally { setPending(false); }
  }

  async function addCandidates() {
    if (!csv.trim()) return;
    setPending(true);
    try {
      const r = await api.intake(job.id, csv);
      setNormSummary(r.summary);
      say(`${r.summary}${r.excluded.length ? " - fix the flagged rows and re-add." : " You can confirm Gate 1 now."}`);
      await reload();
      onBoardChanged?.();
    } catch (e) { say(`Intake failed: ${(e as Error).message}`); }
    finally { setPending(false); }
  }

  async function confirmGate1() {
    setPending(true);
    try {
      await api.confirmJob(job.id);
      say("Gate 1 confirmed. Reading the interviewer's calendar and generating fair slots...");
      const g = await api.generateSlots(job.id);
      say(`${g.eligible} eligible times in the window -> offering ${g.offered} (max 5, spread for fairness). Review the outreach next.`);
      await reload();
      onBoardChanged?.();
    } catch (e) { say(`Couldn't confirm: ${(e as Error).message}`); }
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
    <>
      <GateCard gate="Gate 1 - parameter card" title="Confirm the interview parameters"
        reassurance="No calendar is touched and nothing is sent until you confirm. You need at least one candidate first."
        primaryLabel="Confirm & read calendar" pending={pending}
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
        <div style={{ fontSize: 12, color: nCandidates ? cvar("st-confirmed") : cvar("ink-subtle"), marginTop: 10 }}>
          {nCandidates ? `${nCandidates} candidate${nCandidates === 1 ? "" : "s"} ready` : "No candidates yet - add them below."}
        </div>
      </GateCard>

      <InfoCard>
        <Eyebrow>Candidates</Eyebrow>
        <div style={{ fontSize: 13, color: cvar("ink-muted"), marginBottom: 8 }}>
          Paste one per line as <span className="mono">name, email, timezone</span> (timezone optional - I default it and flag assumptions). A CSV header row is fine.
        </div>
        <textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={4}
          placeholder={"name,email,timezone\nMaya Chen, maya@example.com, Asia/Kolkata\nJon Reed, jon@example.com"}
          style={{ width: "100%", resize: "vertical", border: cvar("hair"), borderRadius: cvar("radius"), padding: 10, fontSize: 13, background: cvar("paper") }} />
        <div style={{ marginTop: 8 }}><Btn onClick={addCandidates} disabled={pending || !csv.trim()}>{pending ? "Adding..." : "Add candidates"}</Btn></div>
        {normSummary && <div style={{ marginTop: 8, fontSize: 12, color: cvar("ink-muted") }}>{normSummary}</div>}
      </InfoCard>
    </>
  );
}

function OutreachGate({
  jobId, say, reload, onBoardChanged,
}: {
  jobId: number; say: (t: string) => void; reload: () => Promise<void>; onBoardChanged?: () => void;
}) {
  const [tpl, setTpl] = useState<api.Template | null>(null);
  const [preview, setPreview] = useState<api.Preview | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => { api.getTemplate(jobId).then(setTpl).catch(() => {}); }, [jobId]);

  async function doPreview() {
    if (!tpl) return;
    try { setPreview(await api.previewOutreach(jobId, tpl.subject, tpl.body)); }
    catch (e) { say(`Preview failed: ${(e as Error).message}`); }
  }
  async function approveSend() {
    if (!tpl) return;
    setPending(true);
    try {
      await api.approveOutreach(jobId, tpl.subject, tpl.body);
      const r = await api.sendOutreach(jobId);
      say(`Sent ${r.sent} invitation${r.sent === 1 ? "" : "s"}. I'll watch for replies and follow up once if it goes quiet. Track live status in the Board tab.`);
      await reload();
      onBoardChanged?.();
    } catch (e) { say(`Send failed: ${(e as Error).message}`); }
    finally { setPending(false); }
  }

  return (
    <GateCard gate="Gate 2 - outreach" title="Send interview invitations"
      reassurance="No emails have been sent. Preview the message, then send to every candidate at once."
      primaryLabel="Approve & send invitations" pending={pending}
      onPrimary={approveSend} onSecondary={doPreview} secondaryLabel={preview ? "Refresh preview" : "Preview email"}>
      {preview ? (
        <div style={{ border: cvar("hair"), borderRadius: cvar("radius"), padding: 12, background: cvar("paper"), fontSize: 12.5 }}>
          <div style={{ color: cvar("ink-subtle"), marginBottom: 6 }}>Preview - as {preview.to} would receive it:</div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>{preview.subject}</div>
          <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.45 }}>{preview.body}</div>
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: cvar("ink-muted") }}>Each candidate is emailed in their own timezone. Preview renders the real email for the first candidate.</div>
      )}
    </GateCard>
  );
}

function RunningPanel({
  jobId, tz, board, say, reload, onBoardChanged,
}: {
  jobId: number; tz: string; board: api.Board | null;
  say: (t: string) => void; reload: () => Promise<void>; onBoardChanged?: () => void;
}) {
  const [active, setActive] = useState<number | null>(null);
  const [res, setRes] = useState<api.ReplyParse | null>(null);
  const [slot, setSlot] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  const [reoffering, setReoffering] = useState(false);

  const cands = board?.candidates ?? [];
  const needReview = cands.filter((c) => ["reply_received", "slots_offered", "followup_sent"].includes(c.status));

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
          <div style={{ fontSize: 13, color: cvar("ink-muted") }}>Everyone's booked or nothing needs you. Check the Board tab for the full picture.</div>
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