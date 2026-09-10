import React from "react";

/* Design primitives for the sage (Direction B) UI. Inline styles read the CSS
   vars in theme.css. These encode the EXA findings so every gate/roster is
   consistent:
   - StatePill: color + glyph + text (never color alone).
   - GateCard: Q1 approval-card anatomy — "Approval required" header, a
     "no action taken yet" reassurance line, and a footer whose PRIMARY button
     names the irreversible action (passed in by the caller, e.g. "Send 2 invites").
   - Proposal vs Confirmation are visually distinct: GateCard (needs you) is
     bordered + accent-tinted; InfoCard (agent proposal / info) is quiet. */

const c = (v: string) => `var(--${v})`;

export function Btn({
  children, onClick, variant = "primary", disabled, title, small,
}: {
  children: React.ReactNode; onClick?: () => void;
  variant?: "primary" | "ghost" | "danger"; disabled?: boolean; title?: string; small?: boolean;
}) {
  const base: React.CSSProperties = {
    border: "none", borderRadius: c("radius"), fontWeight: 500,
    fontSize: small ? 12.5 : 13.5, padding: small ? "6px 12px" : "9px 16px",
    transition: "opacity .12s, transform .05s", opacity: disabled ? 0.45 : 1,
    pointerEvents: disabled ? "none" : "auto", lineHeight: 1.2,
  };
  const styles: Record<string, React.CSSProperties> = {
    primary: { ...base, background: c("accent"), color: "#fff" },
    ghost: { ...base, background: "transparent", color: c("ink-muted"), boxShadow: `inset 0 0 0 1px ${c("hairline-2")}` },
    danger: { ...base, background: "transparent", color: c("st-attention"), boxShadow: `inset 0 0 0 1px var(--st-attention)` },
  };
  return (
    <button style={styles[variant]} onClick={onClick} disabled={disabled} title={title}
      onMouseDown={(e) => (e.currentTarget.style.transform = "scale(.985)")}
      onMouseUp={(e) => (e.currentTarget.style.transform = "scale(1)")}
      onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}>
      {children}
    </button>
  );
}

/* status -> {label, glyph, fg var, bg var}. Single source of truth for the 6 states. */
export const STATE_META: Record<string, { label: string; glyph: string; fg: string; bg: string }> = {
  not_contacted:  { label: "Not contacted", glyph: "○", fg: "st-idle",      bg: "st-idle-bg" },
  slots_offered:  { label: "Slots offered", glyph: "◐", fg: "st-active",    bg: "st-active-bg" },
  followup_sent:  { label: "Follow-up sent", glyph: "◑", fg: "st-active",   bg: "st-active-bg" },
  reply_received: { label: "Reply received", glyph: "↩", fg: "st-review",   bg: "st-review-bg" },
  needs_attention:{ label: "Needs attention", glyph: "!", fg: "st-attention", bg: "st-attention-bg" },
  confirmed:      { label: "Confirmed", glyph: "✓", fg: "st-confirmed",     bg: "st-confirmed-bg" },
};

export function StatePill({ status, small }: { status: string; small?: boolean }) {
  const m = STATE_META[status] ?? { label: status, glyph: "·", fg: "ink-subtle", bg: "surface-2" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontSize: small ? 11 : 11.5, fontWeight: 600, padding: small ? "1px 7px" : "2px 9px",
      borderRadius: 20, color: c(m.fg), background: c(m.bg), whiteSpace: "nowrap",
    }}>
      <span aria-hidden style={{ fontWeight: 700 }}>{m.glyph}</span>{m.label}
    </span>
  );
}

export function InfoCard({ children, tone = "quiet" }: { children: React.ReactNode; tone?: "quiet" | "note" }) {
  return (
    <div style={{
      border: c("hair"), borderRadius: c("radius-lg"),
      background: tone === "note" ? c("surface-2") : c("surface"),
      padding: 14, fontSize: 13.5, lineHeight: 1.5, color: c("ink"),
    }}>{children}</div>
  );
}

/* Q1 approval card. `primaryLabel` MUST name the irreversible action. */
export function GateCard({
  gate, title, reassurance, children, primaryLabel, onPrimary, onSecondary,
  secondaryLabel = "Edit", onReject, rejectLabel, pending, resolved,
}: {
  gate: string; title: string; reassurance?: string; children?: React.ReactNode;
  primaryLabel: string; onPrimary?: () => void;
  onSecondary?: () => void; secondaryLabel?: string;
  onReject?: () => void; rejectLabel?: string;
  pending?: boolean; resolved?: string | null;
}) {
  return (
    <div style={{
      border: `1.5px solid ${c("accent")}`, borderRadius: c("radius-lg"),
      background: c("surface"), overflow: "hidden",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8, padding: "10px 14px",
        background: c("accent-soft"), borderBottom: `1px solid ${c("hairline")}`,
      }}>
        <span aria-hidden style={{ color: c("accent-ink"), fontWeight: 700 }}>◆</span>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: ".04em", textTransform: "uppercase", color: c("accent-ink") }}>
          {gate} · needs you
        </span>
      </div>
      <div style={{ padding: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: reassurance ? 2 : 10 }}>{title}</div>
        {reassurance && (
          <div style={{ fontSize: 12, color: c("ink-muted"), marginBottom: 10 }}>{reassurance}</div>
        )}
        {children}
        {resolved ? (
          <div style={{ marginTop: 12, fontSize: 12.5, color: c("ink-muted") }}>{resolved}</div>
        ) : (
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <Btn onClick={onPrimary} disabled={pending}>{pending ? "Working…" : primaryLabel}</Btn>
            {onSecondary && <Btn variant="ghost" onClick={onSecondary} disabled={pending}>{secondaryLabel}</Btn>}
            {onReject && <Btn variant="danger" onClick={onReject} disabled={pending}>{rejectLabel ?? "Discard"}</Btn>}
          </div>
        )}
      </div>
    </div>
  );
}

export function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <div style={{ borderTop: c("hair"), borderBottom: c("hair"), padding: "10px 0", display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map(([k, v], i) => (
        <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, gap: 12 }}>
          <span style={{ color: c("ink-muted") }}>{k}</span>
          <span className="tnum" style={{ fontWeight: 500, textAlign: "right" }}>{v}</span>
        </div>
      ))}
    </div>
  );
}

export function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 10.5, letterSpacing: ".05em", textTransform: "uppercase", fontWeight: 600, color: c("ink-subtle"), marginBottom: 6 }}>{children}</div>;
}