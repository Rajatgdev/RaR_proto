import { useCallback, useEffect, useState } from "react";
import * as api from "./lib/api";
import { Sidebar } from "./components/Sidebar";
import { JobChat } from "./components/JobChat";
import { Board } from "./components/Board";
import { Dashboard } from "./components/Dashboard";

const cvar = (v: string) => `var(--${v})`;

/* Shell: sidebar of job-chats -> active job with Chat | Board tabs. "New" opens
   a fresh conversational chat (greeting screen, no form). The agent creates the
   job itself from the conversation; we adopt the returned job_id. Chat is fully
   persisted server-side, so switching away and back restores the transcript. */

type Tab = "chat" | "board";
type View =
  | { mode: "dashboard" }
  | { mode: "newchat"; sessionKey: string }   // brand-new conversation, no job yet
  | { mode: "job"; id: number };

export default function App() {
  const [jobs, setJobs] = useState<api.JobSummary[]>([]);
  const [view, setView] = useState<View>({ mode: "dashboard" });
  const [tab, setTab] = useState<Tab>("chat");
  const [status, setStatus] = useState<api.Status>({ connected: false, email: null });
  const [bump, setBump] = useState(0);

  const refreshJobs = useCallback(async () => {
    try { setJobs(await api.listJobs()); } catch { /* ignore */ }
  }, []);

  useEffect(() => { api.getStatus().then(setStatus).catch(() => {}); refreshJobs(); }, [refreshJobs]);

  function openJob(id: number) { setView({ mode: "job", id }); setTab("chat"); }
  function newChat() {
    setView({ mode: "newchat", sessionKey: `s_${Math.random().toString(36).slice(2, 14)}` });
    setTab("chat");
  }
  function onJobCreated(id: number) { refreshJobs(); setView({ mode: "job", id }); }
  const changed = useCallback(() => { setBump((b) => b + 1); refreshJobs(); }, [refreshJobs]);

  const activeId = view.mode === "job" ? view.id : null;
  const active = jobs.find((j) => j.id === activeId) ?? null;
  const greeting = greetingLine();

  return (
    <div style={{ height: "100%", display: "grid", gridTemplateColumns: "210px 1fr" }}>
      <Sidebar jobs={jobs} activeId={activeId}
        onSelect={openJob} onNew={newChat}
        connected={status.connected} email={status.email} />

      <main style={{ display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0, background: cvar("paper") }}>
        {view.mode === "dashboard" ? (
          <Dashboard jobs={jobs} onOpen={openJob} onNew={newChat} />
        ) : view.mode === "newchat" ? (
          <>
            <div style={header}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>New interview</div>
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <JobChat key={view.sessionKey} jobId={null} sessionKey={view.sessionKey}
                greeting={greeting}
                onJobCreated={onJobCreated} onChanged={changed} />
            </div>
          </>
        ) : (
          <>
            <div style={header}>
              <div style={{ fontSize: 14, fontWeight: 600, marginRight: 6 }}>{active?.title ?? "Job"}</div>
              <TabBtn label="Chat" on={tab === "chat"} onClick={() => setTab("chat")} />
              <TabBtn label="Board" on={tab === "board"} onClick={() => setTab("board")} />
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
              {tab === "chat"
                ? <JobChat key={view.id} jobId={view.id} sessionKey={null}
                    onJobCreated={onJobCreated} onChanged={changed} />
                : <Board key={`${view.id}-${bump}`} jobId={view.id} onAct={() => setTab("chat")} />}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

const header: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, borderBottom: "1px solid var(--hairline)",
  padding: "0 18px", height: 46, background: "var(--surface)",
};

function greetingLine() {
  const h = new Date().getHours();
  const part = h < 12 ? "morning" : h < 18 ? "afternoon" : "evening";
  return `Good ${part}.`;
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