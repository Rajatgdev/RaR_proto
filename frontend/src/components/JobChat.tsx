import { useEffect, useRef, useState } from "react";
import * as api from "../lib/api";
import { GateCard, InfoCard, KV, Btn, Eyebrow } from "./ui";

const cvar = (v: string) => `var(--${v})`;

/* A job-chat. The agent narrates in prose; every external commitment surfaces
   as an inline GateCard (Q1): proposal vs confirmation is a hard visual boundary,
   the primary button names the irreversible action, and pending cards say
   "no action taken yet". Free-text in the composer NEVER resolves a gate — it
   just posts a message; the card's button is the only authorization path. */

type Turn =
  | { who: "user"; text: string }
  | { who: "agent"; text: string }
  | { who: "gate1"; done?: string }                    // parameter card → confirm & read calendar
  | { who: "intake" }                                  // paste candidates
  | { who: "gate2"; done?: string }                    // outreach preview → send invites
  | { who: "reply"; candidateId: number }              // read+parse a candidate reply
  | { who: "reoffer"; candidateId: number; done?: string };

const fmtLocal = (iso: string, tz: string) =>
  new Date(iso).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit", timeZone: tz, timeZoneName: "short",
  });

export function JobChat({
  jobId, seedTurns, onBoardChanged,
}: {
  jobId: number; seedTurns?: Turn[]; onBoardChanged?: () => void;
}) {
  const [job, setJob] = useState<api.JobDetail | null>(null);
  const [turns, setTurns] = useState<Turn[]>(seedTurns ?? []);
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { api.getJob(jobId).then(setJob).catch(() => {}); }, [jobId]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [turns.length]);

  const tz = job?.timezone ?? "UTC";
  const push = (t: Turn) => setTurns((p) => [...p, t]);
  const agent = (text: string) => push({ who: "agent", text });

  // The composer posts a message; it can request an action card but cannot
  // resolve a gate. We keep this deliberately simple for the prototype: typed
  // messages are recorded, and the agent nudges toward the next click-gate.
  function send() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    push({ who: "user", text });
    agent("Noted. Use the card above to take the next action — I don't send or book from chat text alone.");
  }

  /* ---- Gate 1: parameter card ---- */
  function Gate1({ done }: { done?: string }) {
    const [pending, setPending] = useState(false);
    const card = job?.params;
    if (!card) return null;
    async function confirm() {
      setPending(true);
      try {
        await api.confirmJob(jobId);
        setTurns((p) => p.map((t) => (t.who === "gate1" ? { ...t, done: "Confirmed — calendar authorized." } : t)));
        agent("Confirmed. I've read the interviewer's calendar and can generate slots. Paste candidates when ready.");
        push({ who: "intake" });
      } catch (e) { agent(`Couldn't confirm: ${(e as Error).message}`); }
      finally { setPending(false); }
    }
    return (
      <GateCard gate="Gate 1 · parameter card" title="Confirm the interview parameters"
        reassurance="No calendar is touched until you confirm. Nothing has been sent."
        primaryLabel="Confirm & read calendar" pending={pending} resolved={done}
        onPrimary={confirm}>
        <KV rows={[
          ["Role", card.job_title],
          ["Duration", `${card.duration_min} min`],
          ["Hours", `${card.work_start}–${card.work_end}`],
          ["Window", `${card.window_days} days`],
          ["Interviewer", (card.interviewers?.[0]?.name) ?? "—"],
        ]} />
      </GateCard>
    );
  }

  /* ---- Intake: paste candidates ---- */
  function Intake() {
    const [csv, setCsv] = useState("");
    const [pending, setPending] = useState(false);
    const [summary, setSummary] = useState<string | null>(null);
    async function submit() {
      if (!csv.trim()) return;
      setPending(true);
      try {
        const r = await api.intake(jobId, csv);
        setSummary(r.summary);
        if (r.excluded.length === 0 && r.ready.length > 0) {
          agent(`Added ${r.ready.length} candidate${r.ready.length === 1 ? "" : "s"}. Generating fair slots…`);
          const g = await api.generateSlots(jobId);
          agent(`${g.eligible} eligible times in the window → offering ${g.offered} (max 5, spread for fairness). Review the outreach below.`);
          push({ who: "gate2" });
        }
      } catch (e) { agent(`Intake failed: ${(e as Error).message}`); }
      finally { setPending(false); }
    }
    return (
      <InfoCard>
        <Eyebrow>Candidates</Eyebrow>
        <div style={{ fontSize: 13, color: cvar("ink-muted"), marginBottom: 8 }}>
          Paste one per line as <span className="mono">name, email, timezone</span> (timezone optional — I default it and flag assumptions).
        </div>
        <textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={4}
          placeholder={"Maya Chen, maya@example.com, Asia/Kolkata\nJon Reed, jon@example.com"}
          style={{ width: "100%", resize: "vertical", border: cvar("hair"), borderRadius: cvar("radius"),
            padding: 10, fontSize: 13, background: cvar("paper") }} />
        <div style={{ marginTop: 8 }}><Btn onClick={submit} disabled={pending}>{pending ? "Adding…" : "Add candidates"}</Btn></div>
        {summary && <div style={{ marginTop: 8, fontSize: 12, color: cvar("ink-muted") }}>{summary}</div>}
      </InfoCard>
    );
  }

  /* ---- Gate 2: outreach preview → send ---- */
  function Gate2({ done }: { done?: string }) {
    const [pending, setPending] = useState(false);
    const [preview, setPreview] = useState<api.Preview | null>(null);
    const [tpl, setTpl] = useState<api.Template | null>(null);
    useEffect(() => { api.getTemplate(jobId).then(setTpl).catch(() => {}); }, []);
    async function doPreview() {
      if (!tpl) return;
      try { setPreview(await api.previewOutreach(jobId, tpl.subject, tpl.body)); }
      catch (e) { agent(`Preview failed: ${(e as Error).message}`); }
    }
    async function approveSend() {
      if (!tpl) return;
      setPending(true);
      try {
        await api.approveOutreach(jobId, tpl.subject, tpl.body);
        const r = await api.sendOutreach(jobId);
        setTurns((p) => p.map((t) => (t.who === "gate2" ? { ...t, done: `Sent ${r.sent} invitation${r.sent === 1 ? "" : "s"}. Candidates moved to "slots offered".` } : t)));
        agent(`Sent ${r.sent} invitation${r.sent === 1 ? "" : "s"}. I'll watch for replies and follow up once if there's silence. Check the Board tab for live status.`);
        onBoardChanged?.();
      } catch (e) { agent(`Send failed: ${(e as Error).message}`); }
      finally { setPending(false); }
    }
    const n = preview ? 1 : 0; // preview renders for first candidate; send goes to all not_contacted
    return (
      <GateCard gate="Gate 2 · outreach" title="Send interview invitations"
        reassurance="No emails have been sent. Review the message, then send."
        primaryLabel="Approve & send invitations" pending={pending} resolved={done}
        onPrimary={approveSend} onSecondary={doPreview} secondaryLabel={preview ? "Refresh preview" : "Preview email"}>
        {preview ? (
          <div style={{ border: cvar("hair"), borderRadius: cvar("radius"), padding: 12, background: cvar("paper"), fontSize: 12.5 }}>
            <div style={{ color: cvar("ink-subtle"), marginBottom: 6 }}>Preview — as {preview.to} would receive it{n ? "" : ""}:</div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{preview.subject}</div>
            <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.45 }}>{preview.body}</div>
          </div>
        ) : (
          <div style={{ fontSize: 12.5, color: cvar("ink-muted") }}>Preview renders the real email for the first candidate. Each candidate is emailed in their own timezone.</div>
        )}
      </GateCard>
    );
  }

  /* ---- Reply: read + parse a candidate reply → propose (confirm-book) or escalate ---- */
  function ReplyCard({ candidateId }: { candidateId: number }) {
    const [pending, setPending] = useState(false);
    const [res, setRes] = useState<api.ReplyParse | null>(null);
    const [slot, setSlot] = useState<number | null>(null);
    const [booked, setBooked] = useState<string | null>(null);

    async function read() {
      setPending(true);
      try {
        const r = await api.parseReply(jobId, candidateId);
        setRes(r);
        if (r.status === "confirm" && r.proposed_slots?.length) setSlot(r.proposed_slots[0].slot_id);
        if (r.status === "escalate") {
          agent("This reply didn't map cleanly to an offered slot — it looks like they proposed a different time. You can re-offer times near their preference.");
          push({ who: "reoffer", candidateId });
        }
      } catch (e) { agent(`Couldn't read reply: ${(e as Error).message}`); }
      finally { setPending(false); }
    }
    async function book() {
      if (slot == null) return;
      setPending(true);
      try {
        const b = await api.confirmBooking(jobId, candidateId, slot);
        setBooked(`Booked ${b.when} · Meet: ${b.meet_link}`);
        agent(`Booked. Calendar event created and both parties emailed. ${b.when}.`);
        onBoardChanged?.();
      } catch (e) { agent(`Booking failed: ${(e as Error).message}`); }
      finally { setPending(false); }
    }

    if (!res) {
      return <InfoCard><Eyebrow>Candidate reply</Eyebrow>
        <div style={{ fontSize: 13, color: cvar("ink-muted"), marginBottom: 8 }}>Read the latest reply and parse it (one LLM call). I never book from this — you confirm.</div>
        <Btn onClick={read} disabled={pending}>{pending ? "Reading…" : "Read & parse reply"}</Btn>
      </InfoCard>;
    }
    if (res.status === "no_reply") return <InfoCard tone="note">No candidate reply in the thread yet.</InfoCard>;
    if (res.status === "escalate")
      return <InfoCard tone="note"><Eyebrow>Escalated</Eyebrow>{res.note ?? res.reason ?? "Needs manual review."} — see the re-offer card below.</InfoCard>;

    // confirm → the human commits
    return (
      <GateCard gate="Confirm booking" title="Book the slot the candidate chose"
        reassurance="No event is created until you confirm. This will create a calendar event and email both parties."
        primaryLabel="Create event & notify both" pending={pending} resolved={booked}
        onPrimary={book}>
        {res.reply_body && (
          <div style={{ fontSize: 12.5, color: cvar("ink-muted"), marginBottom: 10, whiteSpace: "pre-wrap",
            borderLeft: `2px solid ${cvar("hairline-2")}`, paddingLeft: 10 }}>
            {res.reply_body.slice(0, 240)}
          </div>
        )}
        <div style={{ fontSize: 12.5, marginBottom: 8, color: cvar("ink-muted") }}>
          Parsed confidence {typeof res.confidence === "number" ? res.confidence.toFixed(2) : "—"} · pick the slot to book:
        </div>
        <select value={slot ?? undefined} onChange={(e) => setSlot(Number(e.target.value))}
          style={{ width: "100%", border: cvar("hair"), borderRadius: cvar("radius"), padding: "8px 10px", fontSize: 13, background: cvar("paper") }}>
          {(res.proposed_slots ?? []).map((s) => (
            <option key={s.slot_id} value={s.slot_id}>{fmtLocal(s.start, tz)}</option>
          ))}
        </select>
      </GateCard>
    );
  }

  /* ---- Re-offer (Case 2): propose slots near candidate's requested time ---- */
  function ReofferCard({ candidateId, done }: { candidateId: number; done?: string }) {
    const [pending, setPending] = useState(false);
    async function go() {
      setPending(true);
      try {
        const r = await api.reoffer(jobId, candidateId);
        setTurns((p) => p.map((t) => (t.who === "reoffer" && t.candidateId === candidateId
          ? { ...t, done: `Sent ${r.slots_offered} times near ${r.target_time}.` } : t)));
        agent(`Re-offered ${r.slots_offered} times near their preference (${r.target_time}), within the job's rules. Watching for their reply.`);
        onBoardChanged?.();
      } catch (e) { agent(`Re-offer failed: ${(e as Error).message}`); }
      finally { setPending(false); }
    }
    return (
      <GateCard gate="Re-offer · review required" title="Propose the closest available times"
        reassurance="Draft — nothing sent yet. I'll email 5 valid times nearest their request, respecting the job's hours."
        primaryLabel="Approve & send re-offer" pending={pending} resolved={done}
        onPrimary={go}>
        <div style={{ fontSize: 12.5, color: cvar("ink-muted") }}>
          The candidate asked for a time outside what was offered. I'll find the nearest slots that still fit the interview rules and send them.
        </div>
      </GateCard>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{ flex: 1, overflow: "auto", padding: "22px 22px" }}>
        <div style={{ maxWidth: 560, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {turns.map((t, i) => {
            if (t.who === "user")
              return <div key={i} style={{ display: "flex", justifyContent: "flex-end" }}>
                <div style={{ maxWidth: "82%", background: cvar("accent"), color: "#fff", padding: "9px 13px",
                  borderRadius: "14px 14px 4px 14px", fontSize: 13.5, lineHeight: 1.4 }}>{t.text}</div>
              </div>;
            if (t.who === "agent")
              return <div key={i} style={{ fontSize: 13.5, lineHeight: 1.55, maxWidth: "90%", color: cvar("ink") }}>{t.text}</div>;
            if (t.who === "gate1") return <Gate1 key={i} done={t.done} />;
            if (t.who === "intake") return <Intake key={i} />;
            if (t.who === "gate2") return <Gate2 key={i} done={t.done} />;
            if (t.who === "reply") return <ReplyCard key={i} candidateId={t.candidateId} />;
            if (t.who === "reoffer") return <ReofferCard key={i} candidateId={t.candidateId} done={t.done} />;
            return null;
          })}
          <div ref={endRef} />
        </div>
      </div>
      <div style={{ borderTop: cvar("hair"), background: cvar("paper"), padding: "12px 16px" }}>
        <div style={{ maxWidth: 560, margin: "0 auto", display: "flex", gap: 8, alignItems: "flex-end",
          border: cvar("hair"), borderRadius: cvar("radius-lg"), background: cvar("surface"), padding: 8 }}>
          <textarea value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            rows={1} placeholder="Message the agent…"
            style={{ flex: 1, resize: "none", border: "none", outline: "none", background: "transparent",
              fontSize: 13.5, padding: "6px 8px", maxHeight: 120 }} />
          <Btn small onClick={send} disabled={!input.trim()}>Send</Btn>
        </div>
      </div>
    </div>
  );
}

export type { Turn };