const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export const loginUrl = () => `${BASE}/auth/google/login`;

export type Status = { connected: boolean; email: string | null };
export type Slot = { start: string; end: string };
export type Availability = { calendar: string; count: number; slots: Slot[] };

export type Card = {
  job_title: string;
  duration_min: number;
  format: string;
  window_days: number;
  work_start: string;
  work_end: string;
  buffer_min: number;
  max_per_interviewer_per_day: number;
  interviewers: { name: string; email: string | null }[];
  note: string;
};
export type Job = { job_id: number; session_id: number; card: Card; status: string };
export type NormResult = {
  ready: { name: string | null; email: string; timezone: string; timezone_assumed: boolean }[];
  excluded: { email?: string | null; reason: string }[];
  summary: string;
};

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `${r.status}`);
  return r.json();
}

export const getStatus = () => fetch(`${BASE}/auth/google/status`).then(j<Status>);

export const createJob = (request: string, timezone: string) =>
  fetch(`${BASE}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request, timezone }),
  }).then(j<Job>);

export const updateCard = (jobId: number, card: Card) =>
  fetch(`${BASE}/jobs/${jobId}/card`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ card }),
  }).then(j<{ job_id: number; card: Card }>);

export const intake = (jobId: number, csv: string) =>
  fetch(`${BASE}/jobs/${jobId}/candidates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ csv }),
  }).then(j<NormResult>);

export const confirmJob = (jobId: number) =>
  fetch(`${BASE}/jobs/${jobId}/confirm`, { method: "POST" }).then(
    j<{ job_id: number; status: string }>
  );

export const getAvailability = (jobId: number) =>
  fetch(`${BASE}/availability?job_id=${jobId}`).then(j<Availability>);