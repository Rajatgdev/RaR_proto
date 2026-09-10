import { useEffect, useRef, useState } from "react";
import * as api from "../lib/api";
import { Btn, GateCard, KV } from "./ui";

const c = (v: string) => `var(--${v})`;

/* Conversational surface. Everything is a persisted chat turn from POST /chat:
   user bubbles, agent prose, and inline approval cards for gated actions. The
   card's button hits the exact backend endpoint the orchestrator named — chat
   text can never fire a gate. On first message (no job yet) the agent may create
   the job; we adopt the returned job_id and history re-parents server-side. */

type Turn = { role: "user" | "agent"; content: string; card: api.ChatCard | null; pending?: boolean };

export function JobChat({
  jobId, sessionKey, seedMessage, onJobCreated, onChanged,
}: {
  jobId: number | null;
  sessionKey: string | null;
  seedMessage?: string;
  onJobCreated: (id: number) => void;
  onChanged: () => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [jid, setJid] = useState<number | null>(jobId);
  const [skey, setSkey] = useState<string | null>(sessionKey);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const seeded = useRef(false);

  const scroll = () => setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 40);

  useEffect(() => {
    setJid(jobId); setSkey(sessionKey);
    if (jobId == null && !sessionKey) { setTurns([]); setLoaded(true); return; }
    api.getChatHistory(jobId, sessionKey)
      .then((h) => setTurns(h.turns.map((t) => ({ role: t.role, content: t.content, card: t.card }))))
      .catch(() => setTurns([]))
      .finally(() => { setLoaded(true); scroll(); });
  }, [jobId, sessionKey]);

  useEffect(() => {
    if (loaded && seedMessage && !seeded.current && turns.length === 0) {
      seeded.current = true;
      void send(seedMessage);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, seedMessage]);

  async function send(textIn: string) {
    const msg = textIn.trim();
    if (!msg || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", content: msg, card: null },
                            { role: "agent", content: "", card: null, pending: true }]);
    setBusy(true); scroll();
    try {
      const r = await api.chat(msg, jid, skey);
      setSkey(r.session_key);
      if (r.created_job && r.job_id != null) { setJid(r.job_id); onJobCreated(r.job_id); }
      else if (r.job_id != null) setJid(r.job_id);
      setTurns((t) => {
        const copy = [...t];
        copy[copy.length - 1] = { role: "agent", content: r.reply, card: r.card };
        return copy;
      });
      onChanged();
    } catch (e) {
      setTurns((t) => {
        const copy = [...t];
        copy[copy.length - 1] = { role: "agent", content: `(error: ${e instanceof Error ? e.message : e})`, card: null };
        return copy;
      });
    } finally { setBusy(false); scroll(); }
  }

  async function approveCard(idx: number, card: api.ChatCard) {
    setTurns((t) => t.map((x, i) => (i === idx ? { ...x, pending: true } : x)));
    try {
      if (card.action === "approve_and_send" && (card.preview as any)?.requires_approve_first && jid != null) {
        const pv = card.preview as { subject?: string; body?: string };
        await api.approveOutreach(jid, pv.subject ?? "", pv.body ?? "");
      }
      await api.runCardAction(card);
      setTurns((t) => t.map((x, i) =>
        i === idx ? { ...x, pending: false, card: { ...card, no_action_taken: false } } : x));
      onChanged();
      await send(resultPrompt(card.action));
    } catch (e) {
      setTurns((t) => t.map((x, i) =>
        i === idx ? { ...x, pending: false, content: x.content + `\n(couldn't complete: ${e instanceof Error ? e.message : e})` } : x));
    }
  }

  if (!loaded) return <div style={{ padding: 24, color: c("ink-muted") }}>Loading…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 0" }}>
        <div style={{ maxWidth: 720, margin: "0 auto", padding: "0 20px", display: "flex", flexDirection: "column", gap: 18 }}>
          {turns.map((t, i) => (
            <TurnView key={i} turn={t} onApprove={(card) => approveCard(i, card)} />
          ))}
          <div ref={endRef} />
        </div>
      </div>

      <div style={{ borderTop: `1px solid ${c("hairline")}`, padding: "14px 20px" }}>
        <div style={{ maxWidth: 720, margin: "0 auto", display: "flex", gap: 8 }}>
          <input
            value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }}
            placeholder="Message the agent…"
            style={{
              flex: 1, padding: "11px 14px", fontSize: 14, borderRadius: c("radius"),
              border: `1px solid ${c("hairline")}`, background: c("surface"), color: c("ink"),
            }} />
          <Btn onClick={() => void send(input)} disabled={busy || !input.trim()}>Send</Btn>
        </div>
      </div>
    </div>
  );
}

function TurnView({ turn, onApprove }: { turn: Turn; onApprove: (card: api.ChatCard) => void }) {
  if (turn.role === "user") {
    return (
      <div style={{ alignSelf: "flex-end", maxWidth: "80%" }}>
        <div style={{
          background: c("accent"), color: "#fff", padding: "10px 14px",
          borderRadius: 16, borderBottomRightRadius: 4, fontSize: 14, lineHeight: 1.5,
        }}>{turn.content}</div>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {turn.pending ? (
        <div style={{ color: c("ink-muted"), fontSize: 14 }}>…</div>
      ) : (
        turn.content && (
          <div style={{ fontSize: 14, lineHeight: 1.6, color: c("ink"), whiteSpace: "pre-wrap" }}>{turn.content}</div>
        )
      )}
      {turn.card && <ApprovalCard card={turn.card} pending={turn.pending} onApprove={onApprove} />}
    </div>
  );
}

function ApprovalCard({ card, pending, onApprove }: {
  card: api.ChatCard; pending?: boolean; onApprove: (card: api.ChatCard) => void;
}) {
  const resolved = card.no_action_taken === false;
  const rows = previewRows(card);
  return (
    <GateCard
      gate={gateLabel(card.action)}
      title={card.title}
      reassurance={resolved ? undefined : `${card.effect} No action taken yet.`}
      primaryLabel={primaryLabel(card)}
      onPrimary={() => onApprove(card)}
      pending={pending}
      resolved={resolved ? "\u2713 Done." : null}
    >
      {rows.length > 0 && <KV rows={rows} />}
    </GateCard>
  );
}

function gateLabel(a: string) {
  return a === "confirm_gate1" ? "Gate 1 \u00b7 Parameter card"
    : a === "approve_and_send" ? "Gate 2 \u00b7 Outreach"
    : a === "book" ? "Confirm booking"
    : a === "reoffer" ? "Re-offer times" : "Approval";
}
function primaryLabel(card: api.ChatCard) {
  if (card.action === "confirm_gate1") return "Confirm parameters";
  if (card.action === "approve_and_send") return "Approve & send invitations";
  if (card.action === "book") return "Confirm & book";
  if (card.action === "reoffer") return "Send alternative times";
  return "Confirm";
}
function resultPrompt(a: string) {
  return a === "confirm_gate1" ? "I've confirmed Gate 1 \u2014 what's next?"
    : a === "approve_and_send" ? "Invitations sent \u2014 show me the status."
    : a === "book" ? "Booked \u2014 confirm it went through."
    : "Done \u2014 what's next?";
}
function previewRows(card: api.ChatCard): [string, React.ReactNode][] {
  const p = card.preview as Record<string, any>;
  const rows: [string, React.ReactNode][] = [];
  if (card.action === "approve_and_send" && p?.subject) rows.push(["Subject", String(p.subject)]);
  if (card.action === "book") {
    if (p?.slot_id) rows.push(["Slot", `#${p.slot_id}`]);
    if (p?.candidate_id) rows.push(["Candidate", `#${p.candidate_id}`]);
  }
  return rows;
}