import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./lib/api";
import { Sidebar, NewJob } from "./components/Sidebar";
import { JobChat, type Turn } from "./components/JobChat";
import { Board } from "./components/Board";

const cvar = (v: string) => `var(--${v})`;

/* Shell: sidebar of job-chats → active job with Chat | Board tabs. "New" opens
   the NewJob composer; on create, we open the job's chat seeded with its Gate-1
   parameter card. A board-changed bump lets the Board reload after chat actions. */

type Tab = "chat" | "board";

export default function App() {
  const [jobs, setJobs] = useState<api.JobSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<Tab>("chat");
  const [status, setStatus] = useState<api.Status>({ connected: false, email: null });
  const [bump, setBump] = useState(0);
  // seed turns per newly created job so its chat opens on the Gate-1 card
  const seeds = useRef<Record<number, Turn[]>>({});

  const refreshJobs = useCallback(async () => {
    try { setJobs(await api.listJobs()); } catch { /* ignore */ }
  }, []);

  useEffect(() => { api.getStatus().then(setStatus).catch(() => {}); refreshJobs(); }, [refreshJobs]);

  function openJob(id: number) { setActiveId(id); setCreating(false); setTab("chat"); }

  function onCreated(id: number) {
    seeds.current[id] = [
      { who: "agent", text: "Here's the parameter card I parsed from your request. Review it and confirm — nothing touches the calendar until you do." },
      { who: "gate1" },
    ];
    refreshJobs();
    openJob(id);
  }

  const boardChanged = useCallback(() => { setBump((b) => b + 1); refreshJobs(); }, [refreshJobs]);

  const active = jobs.find((j) => j.id === activeId) ?? null;

  return (
    <div style={{ height: "100%", display: "grid", gridTemplateColumns: "210px 1fr" }}>
      <Sidebar jobs={jobs} activeId={creating ? null : activeId}
        onSelect={openJob} onNew={() => { setCreating(true); setActiveId(null); }}
        connected={status.connected} email={status.email} />

      <main style={{ display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0, background: cvar("paper") }}>
        {creating ? (
          <NewJob onCreated={onCreated} />
        ) : activeId == null ? (
          <Empty connected={status.connected} />
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 12, borderBottom: cvar("hair"),
              padding: "0 18px", height: 46, background: cvar("surface") }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginRight: 6 }}>{active?.title ?? "Job"}</div>
              <TabBtn label="Chat" on={tab === "chat"} onClick={() => setTab("chat")} />
              <TabBtn label="Board" on={tab === "board"} onClick={() => { setTab("board"); }} />
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
              {tab === "chat"
                ? <JobChat key={activeId} jobId={activeId} seedTurns={seeds.current[activeId]} onBoardChanged={boardChanged} />
                : <Board key={`${activeId}-${bump}`} jobId={activeId} onAct={() => setTab("chat")} />}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function TabBtn({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      border: "none", background: "transparent", fontSize: 12.5, padding: "6px 10px",
      borderRadius: cvar("radius"), color: on ? cvar("ink") : cvar("ink-subtle"),
      fontWeight: on ? 600 : 500, boxShadow: on ? `inset 0 0 0 1px ${cvar("hairline-2")}` : "none",
    }}>{label}</button>
  );
}

function Empty({ connected }: { connected: boolean }) {
  return (
    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ maxWidth: 380, textAlign: "center" }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>Scheduling agent</div>
        <div style={{ fontSize: 13.5, color: cvar("ink-muted"), lineHeight: 1.55 }}>
          {connected ? "Pick a job on the left, or start a new one with +." : "Connect Google from the sidebar, then start a job."}
        </div>
      </div>
    </div>
  );
}