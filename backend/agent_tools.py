"""Tool registry for the conversational orchestrator.

Each tool wraps an EXISTING route handler (no logic is reimplemented). Tools are
split into two classes, and this split is the safety model:

  AUTO   — no external side effect. The LLM may call these directly (read state,
           parse the request, edit the card, add candidates, generate slots,
           preview outreach, read a reply).
  GATED  — irreversible / external (confirm Gate 1, approve+send outreach, book,
           re-offer). The LLM may ONLY PROPOSE these. Proposing returns an
           approval-card spec; it NEVER executes. Execution happens only when the
           human clicks the card's button, which hits the real endpoint directly.

So "just send it" typed in chat can never send — the orchestrator, seeing a gated
tool, emits a card instead of calling it. Enforced here, server-side.

Handlers are called directly (not over HTTP) with a Pydantic body + the request's
db session, so there is zero duplication of the endpoint logic.
"""
from typing import Any, Callable

# Import the real handlers + their body models.
from api import jobs as jobs_api
from api import slots as slots_api
from api import outreach as outreach_api
from api import replies as replies_api
from api import board as board_api

AUTO = "auto"
GATED = "gated"


# --- tool implementations (thin adapters over existing handlers) ----------
# Each takes (db, job_id, args) and returns a JSON-serialisable dict. job_id is
# None only for create_job (the pre-job case).

async def _create_job(db, job_id, args):
    body = jobs_api.CreateJob(request=args["request"],
                              timezone=args.get("timezone") or "Europe/Dublin")
    return await jobs_api.create_job(body, db)


async def _update_card(db, job_id, args):
    body = jobs_api.UpdateCard(card=args["card"])
    return await jobs_api.update_card(job_id, body, db)


async def _add_candidates(db, job_id, args):
    body = jobs_api.Intake(csv=args.get("csv"), candidates=args.get("candidates"))
    return await jobs_api.intake(job_id, body, db)


async def _generate_slots(db, job_id, args):
    return await slots_api.generate(job_id, db)


async def _preview_outreach(db, job_id, args):
    body = outreach_api.Approve(subject=args["subject"], body=args["body"])
    return await outreach_api.preview(job_id, body, db)


async def _get_template(db, job_id, args):
    return await outreach_api.get_template(job_id, db)


async def _read_reply(db, job_id, args):
    return await replies_api.parse_candidate_reply(job_id, args["candidate_id"], db)


async def _get_state(db, job_id, args):
    """Compact current-state snapshot for the LLM: board + recent events."""
    board = await board_api.board(job_id, db)
    events = await jobs_api.job_events(job_id, db)
    return {"board": board, "events": events}


# --- gated tools: PROPOSE ONLY. These return a card, never execute. -------
# The card payload tells the frontend which real endpoint the button must call.

def _propose(action: str, title: str, effect: str, endpoint: str,
             method: str, payload: dict, preview: dict) -> dict:
    """Build an approval-card proposal (EXA Q1 spec): names the irreversible
    action, states no action has been taken, carries the exact endpoint+payload
    the button will POST."""
    return {
        "card": {
            "kind": "approval",
            "action": action,            # confirm_gate1 | approve_and_send | book | reoffer
            "title": title,              # e.g. "Send 2 invitations?"
            "effect": effect,            # human-readable irreversible effect
            "no_action_taken": True,
            "endpoint": endpoint,        # the REAL route the button hits
            "method": method,
            "payload": payload,          # body for that route
            "preview": preview,          # what the recruiter reviews before clicking
        }
    }


async def _propose_confirm_gate1(db, job_id, args):
    return _propose(
        "confirm_gate1", "Confirm the interview parameters?",
        "Locks the parameter card and authorises calendar reads. Reversible via Edit.",
        f"/jobs/{job_id}/confirm", "POST", {},
        {"note": "Confirms Gate 1 for this job."})


async def _propose_approve_and_send(db, job_id, args):
    tpl = await outreach_api.get_template(job_id, db)
    return _propose(
        "approve_and_send", "Approve outreach & send invitations?",
        "Sends real emails to every candidate and holds their slots. Irreversible.",
        f"/jobs/{job_id}/outreach/send", "POST", {},
        {"subject": tpl["subject"], "body": tpl["body"],
         "requires_approve_first": not tpl["approved"]})


async def _propose_book(db, job_id, args):
    return _propose(
        "book", "Confirm booking & create the calendar event?",
        "Creates a real Google Calendar event with a Meet link and emails both parties. Irreversible.",
        f"/jobs/{job_id}/replies/{args['candidate_id']}/confirm", "POST",
        {"slot_id": args["slot_id"]},
        {"candidate_id": args["candidate_id"], "slot_id": args["slot_id"]})


async def _propose_reoffer(db, job_id, args):
    return _propose(
        "reoffer", "Send alternative times to this candidate?",
        "Emails the candidate a fresh set of nearby slots. Irreversible.",
        f"/jobs/{job_id}/reoffer/{args['candidate_id']}", "POST",
        {"target": args.get("target")},
        {"candidate_id": args["candidate_id"], "target": args.get("target")})


async def _propose_cancel(db, job_id, args):
    return _propose(
        "cancel", "Cancel this candidate's interview?",
        "Deletes the Google Calendar event, notifies both parties, and frees the slot. Irreversible.",
        f"/jobs/{job_id}/replies/{args['candidate_id']}/cancel", "POST",
        {"reason": args.get("reason")},
        {"candidate_id": args["candidate_id"], "reason": args.get("reason")})


# --- the registry ---------------------------------------------------------

class Tool:
    def __init__(self, name: str, cls: str, description: str,
                 parameters: dict, fn: Callable, needs_job: bool = True):
        self.name = name
        self.cls = cls              # AUTO | GATED
        self.description = description
        self.parameters = parameters
        self.fn = fn
        self.needs_job = needs_job

    def schema(self) -> dict:
        """OpenAI function-calling schema."""
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", **self.parameters}}}


def _p(props: dict, required: list[str]) -> dict:
    return {"properties": props, "required": required}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    # --- AUTO ---
    Tool("create_job", AUTO,
         "Create a new interview job from the recruiter's plain-English description. "
         "Call this ONLY once you have at least the role/interviewer/duration. Returns the parameter card.",
         _p({"request": {"type": "string", "description": "the recruiter's full description of the role"},
             "timezone": {"type": "string", "description": "IANA tz, default Europe/Dublin"}},
            ["request"]),
         _create_job, needs_job=False),
    Tool("update_card", AUTO,
         "Edit the parameter card (e.g. change duration, hours, window, title). Pass the full updated card object.",
         _p({"card": {"type": "object", "description": "the complete updated parameter card"}}, ["card"]),
         _update_card),
    Tool("add_candidates", AUTO,
         "Add candidates from CSV text or a manual list; normalises + dedupes them. "
         "Pass either csv (raw text) or candidates (list of {name,email,phone,timezone}).",
         _p({"csv": {"type": "string"},
             "candidates": {"type": "array", "items": {"type": "object"}}}, []),
         _add_candidates),
    Tool("generate_slots", AUTO,
         "Generate the offerable slot pool from the confirmed card (needs Gate 1 confirmed first).",
         _p({}, []), _generate_slots),
    Tool("get_outreach_template", AUTO,
         "Get the current outreach email template (subject/body) for this job.",
         _p({}, []), _get_template),
    Tool("preview_outreach", AUTO,
         "Render the outreach email as the first candidate would receive it (no send). "
         "Pass subject and body to preview edits.",
         _p({"subject": {"type": "string"}, "body": {"type": "string"}}, ["subject", "body"]),
         _preview_outreach),
    Tool("read_reply", AUTO,
         "Read and parse a candidate's latest email reply. Returns propose/escalate + any matched slots.",
         _p({"candidate_id": {"type": "integer"}}, ["candidate_id"]),
         _read_reply),
    Tool("get_state", AUTO,
         "Get the current job state: candidate board (who's in what state) + recent event log. "
         "Call this whenever you need to know where things stand before answering.",
         _p({}, []), _get_state),

    # --- GATED (propose only) ---
    Tool("confirm_gate1", GATED,
         "Propose confirming Gate 1 (lock the parameter card). Returns an approval card; does NOT execute.",
         _p({}, []), _propose_confirm_gate1),
    Tool("approve_and_send", GATED,
         "Propose approving outreach and sending invitations. Returns an approval card; does NOT execute.",
         _p({}, []), _propose_approve_and_send),
    Tool("book_slot", GATED,
         "Propose booking a slot for a candidate (creates event + Meet + confirmations). "
         "Returns an approval card; does NOT execute.",
         _p({"candidate_id": {"type": "integer"}, "slot_id": {"type": "integer"}},
            ["candidate_id", "slot_id"]),
         _propose_book),
    Tool("reoffer", GATED,
         "Propose sending alternative times to a candidate who rejected all offered slots. "
         "Returns an approval card; does NOT execute.",
         _p({"candidate_id": {"type": "integer"}, "target": {"type": "string"}},
            ["candidate_id"]),
         _propose_reoffer),
    Tool("cancel_booking", GATED,
         "Propose cancelling a candidate's confirmed interview (deletes the event, "
         "frees the slot, notifies both). Returns an approval card; does NOT execute.",
         _p({"candidate_id": {"type": "integer"}, "reason": {"type": "string"}},
            ["candidate_id"]),
         _propose_cancel),
]}


def tool_schemas(include_pre_job: bool) -> list[dict]:
    """Schemas to expose to the LLM. Pre-job (no job yet) => only create_job + get_state
    make sense; everything else needs a job."""
    out = []
    for t in TOOLS.values():
        if include_pre_job and t.needs_job:
            continue
        out.append(t.schema())
    return out


def is_gated(name: str) -> bool:
    t = TOOLS.get(name)
    return bool(t and t.cls == GATED)


async def run_tool(name: str, db, job_id: int | None, args: dict) -> dict[str, Any]:
    """Execute an AUTO tool, or build a proposal card for a GATED tool.
    GATED tools NEVER execute here — they only return {'card': ...}."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool {name}"}
    if tool.needs_job and job_id is None:
        return {"error": f"{name} needs a job; create one first"}
    return await tool.fn(db, job_id, args or {})