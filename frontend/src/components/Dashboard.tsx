import * as api from "../lib/api";
import { StatePill, Btn } from "./ui";

const cvar = (v: string) => `var(--${v})`;

/* Preliminary dashboard: aggregate stats across all jobs + a card grid you click
   into. This is the landing surface (no job auto-opened). Calm density per Q2 —
   one number row, then a scannable grid; needs-attention/reply pills surface the
   jobs that want you. */

export function Dashboard({
  jobs, onOpen, onNew,
}: {
  jobs: api.JobSummary[]; onOpen: (id: number) => void; onNew: () => void;
}) {
  const totals = jobs.reduce(
    (m, j) => ({
      candidates: m.candidates + j.candidates,
      booked: m.booked + j.confirmed,
      review: m.review + j.to_review,
      attention: m.attention + j.needs_attention,
      active: m.active + (j.status !== "draft" ? 1 : 0),
    }),
    { candidates: 0, booked: 0, review: 0, attention: 0, active: 0 },
  );

  return (
    <div style={{ height: "100%", overflow: "auto", padding: "26px 30px" }}>
      <div style={{ maxWidth: 900, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>Jobs overview</div>
            <div style={{ fontSize: 13, color: cvar("ink-muted"), marginTop: 2 }}>
              {jobs.length} {jobs.length === 1 ? "job" : "jobs"} · {totals.active} active
            </div>
          </div>
          <Btn onClick={onNew}>+ New job</Btn>
        </div>

        {/* aggregate stat row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 22 }}>
          <Stat label="Candidates" value={totals.candidates} />
          <Stat label="Booked" value={totals.booked} tone="confirmed" />
          <Stat label="To review" value={totals.review} tone={totals.review ? "review" : undefined} />
          <Stat label="Needs attention" value={totals.attention} tone={totals.attention ? "attention" : undefined} />
        </div>

        {/* job grid */}
        {jobs.length === 0 ? (
          <div style={{ border: `1px dashed ${cvar("hairline-2")}`, borderRadius: cvar("radius-lg"),
            padding: 40, textAlign: "center", color: cvar("ink-muted"), fontSize: 13.5 }}>
            No jobs yet. Start one — describe an interview in plain English and I'll parse it.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
            {jobs.map((jb) => {
              const flag = jb.needs_attention > 0 ? "needs_attention" : jb.to_review > 0 ? "reply_received" : null;
              return (
                <button key={jb.id} onClick={() => onOpen(jb.id)} style={{
                  textAlign: "left", border: cvar("hair"), borderRadius: cvar("radius-lg"),
                  background: cvar("surface"), padding: 14, display: "flex", flexDirection: "column", gap: 8,
                  minHeight: 96,
                }}>
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{jb.title}</span>
                    {flag && <StatePill status={flag} small />}
                  </div>
                  <div style={{ fontSize: 12, color: cvar("ink-muted") }}>
                    {jb.status === "draft"
                      ? "Draft · not sent"
                      : `${jb.candidates} candidate${jb.candidates === 1 ? "" : "s"}`}
                  </div>
                  <div style={{ marginTop: "auto", display: "flex", gap: 12, fontSize: 11.5, color: cvar("ink-subtle") }}>
                    {jb.confirmed > 0 && <span>✓ {jb.confirmed} booked</span>}
                    {jb.to_review > 0 && <span style={{ color: cvar("st-review") }}>↩ {jb.to_review} to review</span>}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "confirmed" | "review" | "attention" }) {
  const fg = tone ? cvar(`st-${tone}`) : cvar("ink");
  return (
    <div style={{ border: cvar("hair"), borderRadius: cvar("radius-lg"), background: cvar("surface"), padding: "12px 14px" }}>
      <div className="tnum" style={{ fontSize: 24, fontWeight: 600, color: fg, lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 11.5, color: cvar("ink-muted"), marginTop: 3 }}>{label}</div>
    </div>
  );
}