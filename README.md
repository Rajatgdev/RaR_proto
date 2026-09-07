# Scheduling Agent (prototype)

Interview scheduling agent — Rent a Recruiter suite. Standalone (Mode B),
Google-only. Candidate response is **reply-mode only**: the candidate replies
in free text, the agent parses it with one structured LLM call, and the
recruiter confirms before anything is booked. The agent parses and proposes;
the human commits. Built in phases; see the build plan.

## OAuth scopes (declared from day one, Testing mode)
`calendar` (read/write) + `gmail.send` + `gmail.readonly`. All three are core:
`gmail.readonly` reads the candidate's reply, `gmail.send` sends outreach and
confirmations. The scope set is fixed from Phase 1; only publishing status
(Testing → Verified) changes later. `gmail.readonly` is Restricted → heavier
production verification, out of scope for the build.

## Layout
- `backend/` — FastAPI (OAuth, calendar/email, reply parse, slot logic, booking, status API)
- `backend/jobs/sweep.py` — Railway Cron second service (hold expiry + follow-ups)
- `frontend/` — React + TypeScript (Vite), deployed to Vercel

## Stack
React+TS (Vite) / Vercel · FastAPI / Railway · Neon (serverless Postgres) · Railway Cron

## Reply-mode — the one hard principle
Never auto-book off a parse. One structured LLM call per inbound reply returns
`{windows, confidence, is_availability_answer, note}`. Relative dates resolve
against the job timezone + interview window, not the server clock. At/above the
confidence threshold (config constant, default 0.75) → Confirm/Edit card to the
recruiter → confirmed window intersects existing held/available slots → existing
booking path (hold → calendar event → Meet link → confirmations). Below
threshold, `is_availability_answer:false`, or zero matching slot → escalate to
"Needs attention", recruiter handles manually.

## Local dev
```bash
# db
docker compose up -d db
# backend
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in
python -m db.migrate
uvicorn main:app --reload
# frontend (new shell)
cd frontend && npm install
cp .env.example .env
npm run dev
```

## Phase status
- [x] Phase 0 — skeleton + round trip (browser -> API -> Neon -> back)
- [ ] Phase 1 — Google OAuth (all three scopes) + FreeBusy read
- [ ] Phase 2 — setup, intake, normalisation, Gate 1 (+ full schema)
- [ ] Phase 3 — slots, holds, double-booking safety (atomic claim + UNIQUE backstop)
- [ ] Phase 4 — outreach (Gate 2), reply parse + confidence gate, Confirm/Edit
      card, booking + Meet link + confirmations, low-conf escalation
- [ ] Phase 5 — status board, one follow-up, cron sweep