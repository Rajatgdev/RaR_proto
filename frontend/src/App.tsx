import { useEffect, useState } from "react";
import { latestPing, writePing } from "./lib/api";

// Phase 0: prove the round trip browser -> API -> Neon -> back.
export default function App() {
  const [note, setNote] = useState("hello from the browser");
  const [result, setResult] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    latestPing().then(setResult).catch((e) => setError(String(e)));
  }, []);

  async function onWrite() {
    setError(null);
    try {
      setResult(await writePing(note));
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 640, margin: "4rem auto", padding: "0 1rem" }}>
      <h1>Scheduling Agent — Phase 0</h1>
      <p>Round-trip check: write a value to Neon through the API and read it back.</p>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, padding: 8 }} />
        <button onClick={onWrite} style={{ padding: "8px 16px" }}>Write</button>
      </div>
      {error && <pre style={{ color: "crimson" }}>{error}</pre>}
      <pre style={{ background: "#f4f4f4", padding: 12, marginTop: 16 }}>
        {JSON.stringify(result, null, 2)}
      </pre>
    </main>
  );
}
