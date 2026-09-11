"""Conversational orchestrator — POST /chat.

One turn:
  1. Resolve conversation history (by job_id, or pre-job by session_key).
  2. Ask the tool model (gpt-4o-mini) what to do, with the tool schemas. Loop:
     - AUTO tool  -> execute it (real handler), feed result back, continue.
     - GATED tool -> DON'T execute; collect its approval card and stop the loop.
  3. Ask the prose model (gpt-4.1-mini) to write the human reply, given what
     happened. (Pure Q&A never calls a tool -> straight to prose.)
  4. Persist the user turn and the agent turn; if a job was just created, re-parent
     the pre-job turns onto it.

Safety: gated tools only ever yield a card (agent_tools enforces this). The card
carries the real endpoint the button hits; chat text can never fire it.
"""
import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import agent_tools as tools
from config import settings
from db.session import get_session

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_TOOL_STEPS = 5  # safety bound on the tool loop

_SYSTEM = """You are the Interview Scheduling Agent for a recruiter. You are warm,
concise, and genuinely conversational — answer questions ("what do you do?"),
make small talk briefly, and guide the recruiter through scheduling interviews.

You can DO things by calling tools. Read-only/setup tools run immediately.
Irreversible tools (confirm the parameters, send invitations, book a slot,
re-offer times) are GATED: when you call them you are only PROPOSING — the system
shows the recruiter an approval card with a button, and nothing happens until they
click it. Never claim you have sent/booked/confirmed something from chat alone;
say you've prepared it and the recruiter can confirm on the card.
  
Guidance:
- To start a job you need at least the role, who's interviewing, and the duration.
  Once you have that, call create_job. If details are missing, ask for them.
- THE PIPELINE ORDER (follow it): 1) create_job → show the parsed parameter card
  and let them edit; 2) add_candidates (ask them to paste a CSV or list — you
  CANNOT confirm Gate 1 with zero candidates); 3) ONLY THEN propose confirm_gate1;
  4) generate_slots; 5) preview + approve_and_send; 6) handle replies.
  Do NOT propose confirm_gate1 until at least one candidate has been added — it
  will fail. After create_job, your next step is to ask for candidates.
- Call get_state before answering questions about where things stand.
- After a tool runs, explain the result plainly. Keep replies short.
- If the recruiter says "send it" / "book it" / "confirm" in text, call the
  matching gated tool to surface the card — do not pretend it's done.
  
  """


class ChatIn(BaseModel):
    message: str
    job_id: int | None = None
    session_key: str | None = None


async def _load_history(db, job_id, session_key, limit=20):
    if job_id is not None:
        rows = (await db.execute(
            text("SELECT role, content FROM chat_turn WHERE job_id = :j "
                 "ORDER BY id DESC LIMIT :n"), {"j": job_id, "n": limit})).mappings().all()
    else:
        rows = (await db.execute(
            text("SELECT role, content FROM chat_turn WHERE job_id IS NULL AND session_key = :s "
                 "ORDER BY id DESC LIMIT :n"), {"s": session_key, "n": limit})).mappings().all()
    msgs = [{"role": "assistant" if r["role"] == "agent" else "user",
             "content": r["content"]} for r in reversed(rows)]
    return msgs


async def _store(db, job_id, session_key, role, content, tool_calls=None, card=None):
    await db.execute(
        text("INSERT INTO chat_turn (job_id, session_key, role, content, tool_calls, card) "
             "VALUES (:j, :s, :r, :c, CAST(:tc AS JSONB), CAST(:cd AS JSONB))"),
        {"j": job_id, "s": session_key, "r": role, "c": content or "",
         "tc": json.dumps(tool_calls) if tool_calls else None,
         "cd": json.dumps(card) if card else None})


def _client():
    from openai import OpenAI
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _tool_turn(client, messages, schemas):
    """One tool-model call. Returns the raw message (may contain tool_calls)."""
    return client.chat.completions.create(
        model=settings.LLM_MODEL, messages=messages, tools=schemas or None,
        tool_choice="auto" if schemas else "none", temperature=0)


def _prose(client, system, transcript, outcome_note):
    """Final natural-language reply from the prose model."""
    msgs = [{"role": "system", "content": system}] + transcript
    if outcome_note:
        msgs.append({"role": "system", "content": f"[what just happened]\n{outcome_note}"})
    resp = client.chat.completions.create(
        model=settings.LLM_CHAT_MODEL, messages=msgs, temperature=0.4)
    return resp.choices[0].message.content or ""


def _summarize(name, result):
    """Compact a tool result for the model (avoid dumping huge JSON)."""
    if not isinstance(result, dict):
        return str(result)[:800]
    if "error" in result:
        return f"{name} error: {result['error']}"
    if result.get("card"):
        return f"prepared approval card: {result['card'].get('title')}"
    slim = {k: v for k, v in result.items() if k not in ("credentials",)}
    s = json.dumps(slim, default=str)
    return s[:1200]


@router.post("")
async def chat(body: ChatIn, db: AsyncSession = Depends(get_session)):
    session_key = body.session_key or f"s_{uuid.uuid4().hex[:12]}"
    job_id = body.job_id

    history = await _load_history(db, job_id, session_key)
    transcript = [{"role": "system", "content": _SYSTEM}] + history \
        + [{"role": "user", "content": body.message}]

    client = _client()
    schemas = tools.tool_schemas(include_pre_job=(job_id is None))

    card = None
    outcome_notes = []
    created_job_id = None
    tool_audit = []

    # --- tool loop (blocking OpenAI calls run in threadpool) ---
    for _ in range(MAX_TOOL_STEPS):
        try:
            msg = (await run_in_threadpool(_tool_turn, client, transcript, schemas)).choices[0].message
        except Exception as e:
            outcome_notes.append(f"(tool model unavailable: {type(e).__name__})")
            break

        if not msg.tool_calls:
            break  # model wants to just talk

        # record the assistant tool-call message in the transcript
        transcript.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [{"id": tc.id, "type": "function",
                            "function": {"name": tc.function.name,
                                         "arguments": tc.function.arguments}}
                           for tc in msg.tool_calls]})

        stop = False
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_audit.append({"name": name, "args": args})

            result = await tools.run_tool(name, db, job_id, args)

            # AUTO create_job: adopt the new job_id + re-parent pre-job turns
            if name == "create_job" and isinstance(result, dict) and result.get("job_id"):
                created_job_id = result["job_id"]
                job_id = created_job_id
                schemas = tools.tool_schemas(include_pre_job=False)

            # GATED tool -> a card; stop the loop, human must click
            if isinstance(result, dict) and result.get("card"):
                card = result["card"]
                stop = True

            transcript.append({"role": "tool", "tool_call_id": tc.id,
                               "content": _summarize(name, result)})
            outcome_notes.append(_summarize(name, result))

        if stop:
            break

    # --- prose reply ---
    try:
        reply = await run_in_threadpool(
            _prose, client, _SYSTEM, transcript[1:],  # drop the dup system
            "\n".join(outcome_notes) if outcome_notes else "")
    except Exception:
        reply = ("I've noted that. (I couldn't reach the language model to phrase a "
                 "full reply just now.)")
    if not reply.strip():
        reply = "Done." if outcome_notes else "How can I help with scheduling?"

    # --- persist: re-parent pre-job turns if a job was just created ---
    if created_job_id is not None:
        await db.execute(
            text("UPDATE chat_turn SET job_id = :j WHERE job_id IS NULL AND session_key = :s"),
            {"j": created_job_id, "s": session_key})

    await _store(db, job_id, session_key, "user", body.message)
    await _store(db, job_id, session_key, "agent", reply,
                 tool_calls=tool_audit or None, card=card)
    await db.commit()

    return {"reply": reply, "card": card, "job_id": job_id,
            "session_key": session_key, "created_job": created_job_id is not None}


@router.get("/history")
async def history(job_id: int | None = None, session_key: str | None = None,
                  db: AsyncSession = Depends(get_session)):
    """Full transcript for a job (or a pre-job session) — powers the persisted UI."""
    if job_id is not None:
        rows = (await db.execute(
            text("SELECT role, content, card, created_at FROM chat_turn "
                 "WHERE job_id = :j ORDER BY id"), {"j": job_id})).mappings().all()
    elif session_key:
        rows = (await db.execute(
            text("SELECT role, content, card, created_at FROM chat_turn "
                 "WHERE job_id IS NULL AND session_key = :s ORDER BY id"),
            {"s": session_key})).mappings().all()
    else:
        rows = []
    return {"turns": [{"role": r["role"], "content": r["content"],
                       "card": r["card"], "at": r["created_at"].isoformat()} for r in rows]}