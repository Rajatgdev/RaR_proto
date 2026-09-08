const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export const loginUrl = () => `${BASE}/auth/google/login`;

export type Status = { connected: boolean; email: string | null };

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
  }).then(j<{ job_id: number; card: Card; status: string }>);

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

// --- Phase 3: slots, holds, booking ---
export type GenResult = { eligible: number; offered: number;
  slots: { slot_id: number; start: string; end: string }[] };
export type SlotRow = { slot_id: number; start_ts: string; end_ts: string;
  status: string; hold_expires_at: string | null };

export const generateSlots = (jobId: number) =>
  fetch(`${BASE}/jobs/${jobId}/slots/generate`, { method: "POST" }).then(j<GenResult>);

export const listSlots = (jobId: number) =>
  fetch(`${BASE}/jobs/${jobId}/slots`).then(j<SlotRow[]>);

export const holdSlot = (jobId: number, slotId: number, candidateId: number) =>
  fetch(`${BASE}/jobs/${jobId}/slots/${slotId}/hold`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_id: candidateId }),
  }).then(j<{ slot_id: number; hold_id: string; hold_expires_at: string }>);

export const bookSlot = (jobId: number, slotId: number, candidateId: number, holdId: string) =>
  fetch(`${BASE}/jobs/${jobId}/slots/${slotId}/book`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_id: candidateId, hold_id: holdId }),
  }).then(j<{ slot_id: number; status: string }>);

// --- Phase 4a: outreach + Gate 2 ---
export type Template = { subject: string; body: string; approved: boolean };
export type SendResult = { sent: number;
  candidates: { candidate_id: number; email: string; thread_id: string; held: number }[] };

export const getTemplate = (jobId: number) =>
  fetch(`${BASE}/jobs/${jobId}/outreach/template`).then(j<Template>);

export const approveOutreach = (jobId: number, subject: string, body: string) =>
  fetch(`${BASE}/jobs/${jobId}/outreach/approve`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subject, body }),
  }).then(j<{ job_id: number; approved: boolean; pool_size: number }>);

export const sendOutreach = (jobId: number) =>
  fetch(`${BASE}/jobs/${jobId}/outreach/send`, { method: "POST" }).then(j<SendResult>);