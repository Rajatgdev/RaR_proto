import { useEffect, useState } from "react";
import * as api from "../lib/api";
import { StatePill, Btn, Eyebrow, STATE_META } from "./ui";

const cvar = (v: string) => `var(--${v})`;

/* Q2: one calm roster. Needs-attention + reply-received first; done collapsed;
   a muted distribution line; color always paired with text (StatePill). The
   board is the source of truth — chat carries deltas, this carries the whole. */

const ORDER = ["needs_attention", "reply_received", "followup_sent", "slots_offered", "not_contacted", "confirmed"];

function fmt(iso: string | null, tz: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit", timeZone: tz, timeZoneName: "short",
  });
}

export function Board({ jobId, onAct }: { jobId: number; onAct: (candidateId: number, kind: "read" | "reoffer") => void }) {
  const [board, setBoard] = useState<api.Board | null>(null);
  const [busy, setBusy] = useState(false);
  const [showDone, setShowDone] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function load() {
    try { setBoard(await api.getBoard(jobId)); } catch { /* ignore transient */ }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [jobId]);

  async function sweep() {
    setBusy(true); setNote(null);
    try {
      const r = await api.runSweep(jobId);
      setNote(`Swept — ${r.holds_expired} holds expired, ${r.followups_sent} follow-ups sent.`);
      await load();
    } catch (e) { setNote(`Sweep failed: ${(e as Error).message}`); }
    finally { setBusy(false); }
  }

  if (!board) return <div className="thinking mono" style={{ padding: 24, fontSize: 12, color: cvar("ink-subtle") }}>loading board…</div>;

  const cands = [...board.candidates].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  const counts = cands.reduce<Record<string, number>>((m, c) => ((m[c.status] = (m[c.status] ?? 0) + 1), m), {});
  const active = cands.filter((c) => c.status !== "confirmed");
  const done = cands.filter((c) => c.status === "confirmed");

  const dist = ORDER.filter((s) => counts[s]).map((s) => `${counts[s]} ${STATE_META[s]?.label.toLowerCase() ?? s}`).join(" · ");

  return (
    <div style={{ padding: "18px 22px", overflow: "auto", height: "100%" }}>
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 4 }}>
          <Eyebrow>Pipeline · {cands.length} {cands.length === 1 ? "candidate" : "candidates"}</Eyebrow>
          <div style={{ display: "flex", gap: 8 }}>
            <Btn variant="ghost" small onClick={load} disabled={busy}>Refresh</Btn>
            <Btn variant="ghost" small onClick={sweep} disabled={busy}>{busy ? "Sweeping…" : "Run sweep"}</Btn>
          </div>
        </div>
        {dist && <div style={{ fontSize: 12, color: cvar("ink-muted"), marginBottom: 14 }}>{dist}</div>}
        {note && <div style={{ fontSize: 12, color: cvar("ink-muted"), marginBottom: 12 }}>{note}</div>}

        <div style={{ border: cvar("hair"), borderRadius: cvar("radius-lg"), overflow: "hidden", background: cvar("surface") }}>
          {active.map((c, i) => (
            <Row key={c.candidate_id} c={c} tz={board.timezone} last={i === active.length - 1 && done.length === 0} onAct={onAct} />
          ))}
          {done.length > 0 && (
            <button onClick={() => setShowDone((s) => !s)} style={{
              width: "100%", textAlign: "left", background: cvar("surface-2"), border: "none",
              borderTop: cvar("hair"), padding: "9px 14px", fontSize: 12.5, color: cvar("ink-muted"),
            }}>
              {showDone ? "▾" : "▸"} {done.length} confirmed
            </button>
          )}
          {showDone && done.map((c, i) => (
            <Row key={c.candidate_id} c={c} tz={board.timezone} last={i === done.length - 1} onAct={onAct} />
          ))}
        </div>
      </div>
    </div>
  );
}

function Row({ c, tz, last, onAct }: { c: api.BoardCandidate; tz: string; last: boolean; onAct: (id: number, kind: "read" | "reoffer") => void }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "1.4fr 150px 1fr auto", gap: 12, alignItems: "center",
      padding: "11px 14px", borderBottom: last ? "none" : cvar("hair"),
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13.5, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name ?? "(no name)"}</div>
        <div style={{ fontSize: 11.5, color: cvar("ink-subtle"), overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.email}</div>
      </div>
      <div><StatePill status={c.status} small /></div>
      <div style={{ fontSize: 12, color: cvar("ink-muted") }}>
        {c.booked_start
          ? <>Booked {fmt(c.booked_start, tz)}{c.meet_link && <> · <a href={c.meet_link} target="_blank" rel="noreferrer" style={{ color: cvar("accent-ink") }}>Meet</a></>}</>
          : c.status === "reply_received" ? <span style={{ color: cvar("st-review"), fontWeight: 600 }}>Replied — review</span>
          : c.status === "needs_attention" ? <span style={{ color: cvar("st-attention"), fontWeight: 600 }}>Handle manually</span>
          : <span style={{ color: cvar("ink-subtle") }}>—</span>}
      </div>
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        {(c.status === "slots_offered" || c.status === "followup_sent" || c.status === "reply_received") && (
          <Btn variant="ghost" small onClick={() => onAct(c.candidate_id, "read")}>Read reply</Btn>
        )}
      </div>
    </div>
  );
}