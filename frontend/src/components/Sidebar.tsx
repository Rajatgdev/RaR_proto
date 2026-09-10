import React from "react";
import * as api from "../lib/api";
import { Btn, StatePill } from "./ui";

const cvar = (v: string) => `var(--${v})`;

export function Sidebar({
  jobs, activeId, onSelect, onNew, connected, email,
}: {
  jobs: api.JobSummary[]; activeId: number | null;
  onSelect: (id: number) => void; onNew: () => void;
  connected: boolean; email: string | null;
}) {
  return (
    <aside style={{ display: "flex", flexDirection: "column", minHeight: 0,
      background: cvar("surface-2"), borderRight: cvar("hair") }}>
      <div style={{ padding: "14px 14px 10px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 13.5, fontWeight: 600 }}>Jobs</span>
        <button onClick={onNew} title="New job" style={{ border: "none", background: "transparent",
          color: cvar("accent"), fontSize: 20, lineHeight: 1, padding: 0 }}>+</button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "4px 8px", display: "flex", flexDirection: "column", gap: 2 }}>
        {jobs.length === 0 && (
          <div style={{ padding: 10, fontSize: 12.5, color: cvar("ink-subtle") }}>No jobs yet. Start one with +.</div>
        )}
        {jobs.map((jb) => {
          const active = jb.id === activeId;
          const sub = jb.status === "draft"
            ? "draft · not sent"
            : `${jb.candidates} candidate${jb.candidates === 1 ? "" : "s"}`
              + (jb.confirmed ? ` · ${jb.confirmed} booked` : "")
              + (jb.to_review ? ` · ${jb.to_review} to review` : "");
          return (
            <button key={jb.id} onClick={() => onSelect(jb.id)} style={{
              textAlign: "left", border: "none", borderRadius: cvar("radius"), padding: "8px 10px",
              background: active ? cvar("surface") : "transparent",
              boxShadow: active ? `inset 0 0 0 1px ${cvar("hairline-2")}` : "none",
              display: "flex", flexDirection: "column", gap: 3,
            }}>
              <span style={{ fontSize: 13, fontWeight: active ? 600 : 500, color: cvar("ink"),
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{jb.title}</span>
              <span style={{ fontSize: 11, color: cvar("ink-subtle"),
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</span>
              {(jb.needs_attention > 0 || jb.to_review > 0) && (
                <span style={{ marginTop: 2 }}>
                  <StatePill status={jb.needs_attention > 0 ? "needs_attention" : "reply_received"} small />
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div style={{ borderTop: cvar("hair"), padding: "10px 14px", fontSize: 11.5, color: cvar("ink-subtle") }}>
        {connected
          ? <>Google · <span style={{ color: cvar("ink-muted") }}>{email}</span></>
          : <a href={api.loginUrl()} style={{ color: cvar("accent-ink") }}>Connect Google</a>}
      </div>
    </aside>
  );
}

/* New-job composer: agent lists what it needs, recruiter provides the plain-English request. */
export function NewJob({ onCreated }: { onCreated: (jobId: number) => void }) {
  const [req, setReq] = React.useState("");
  const [tz, setTz] = React.useState("Asia/Kolkata");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  async function create() {
    if (!req.trim() || busy) return;
    setBusy(true); setErr(null);
    try {
      const j = await api.createJob(req, tz);
      onCreated(j.job_id);
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{ flex: 1, overflow: "auto", padding: "26px 22px" }}>
        <div style={{ maxWidth: 560, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ fontSize: 13.5, lineHeight: 1.55 }}>
            Hi — let's set up a new interview. Tell me about it in your own words. It helps if you mention the{" "}
            <b>role</b>, who's <b>interviewing</b>, how <b>long</b>, any <b>hours</b> to keep to (like mornings only),
            and the <b>window</b> to book within. I'll turn it into a parameter card you can check before anything happens.
          </div>
          <div style={{ fontSize: 12.5, color: cvar("ink-muted") }}>
            Example: “45-minute frontend designer screen with Sarah, mornings only, over the next two weeks.”
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5, color: cvar("ink-muted") }}>
            <span>Interviewer timezone</span>
            <input value={tz} onChange={(e) => setTz(e.target.value)} className="mono"
              style={{ border: cvar("hair"), borderRadius: cvar("radius"), padding: "5px 8px", fontSize: 12,
                background: cvar("surface"), width: 160 }} />
          </div>
          {err && <div style={{ color: cvar("st-attention"), fontSize: 12.5 }}>{err}</div>}
        </div>
      </div>
      <div style={{ borderTop: cvar("hair"), background: cvar("paper"), padding: "12px 16px" }}>
        <div style={{ maxWidth: 560, margin: "0 auto", display: "flex", gap: 8, alignItems: "flex-end",
          border: cvar("hair"), borderRadius: cvar("radius-lg"), background: cvar("surface"), padding: 8 }}>
          <textarea value={req} onChange={(e) => setReq(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); create(); } }}
            rows={1} placeholder="Describe the interview…"
            style={{ flex: 1, resize: "none", border: "none", outline: "none", background: "transparent",
              fontSize: 13.5, padding: "6px 8px", maxHeight: 120 }} />
          <Btn small onClick={create} disabled={busy || !req.trim()}>{busy ? "Parsing…" : "Send"}</Btn>
        </div>
      </div>
    </div>
  );
}