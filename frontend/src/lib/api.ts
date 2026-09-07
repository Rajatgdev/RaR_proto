const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export const loginUrl = () => `${BASE}/auth/google/login`;

export type Status = { connected: boolean; email: string | null };
export type Slot = { start: string; end: string };
export type Availability = { calendar: string; count: number; slots: Slot[] };

export async function getStatus(): Promise<Status> {
  const r = await fetch(`${BASE}/auth/google/status`);
  if (!r.ok) throw new Error(`status ${r.status}`);
  return r.json();
}

export async function getAvailability(): Promise<Availability> {
  const r = await fetch(`${BASE}/availability`);
  if (!r.ok) throw new Error((await r.json()).detail ?? `availability ${r.status}`);
  return r.json();
}