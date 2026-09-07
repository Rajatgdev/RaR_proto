const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export async function writePing(note: string) {
  const r = await fetch(`${BASE}/ping`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  if (!r.ok) throw new Error(`POST /ping ${r.status}`);
  return r.json();
}

export async function latestPing() {
  const r = await fetch(`${BASE}/ping`);
  if (!r.ok) throw new Error(`GET /ping ${r.status}`);
  return r.json();
}
