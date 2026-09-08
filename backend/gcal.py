"""Google I/O: OAuth flow, credential (de)serialisation/refresh, FreeBusy.

Kept separate from the pure slot math in availability.py. All calls here are
synchronous (googleapiclient / google-auth); routes wrap them in a threadpool.
"""
import os

# Google sometimes returns a superset of the requested scopes (e.g. openid);
# relax so oauthlib doesn't raise "Scope has changed".
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google.auth.transport.requests import Request  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from google_auth_oauthlib.flow import Flow  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402

from config import settings  # noqa: E402


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }


def build_flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        _client_config(), scopes=settings.GOOGLE_SCOPES, state=state
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow


def credentials_from_json(info: str | dict) -> Credentials:
    if isinstance(info, str):
        import json

        info = json.loads(info)
    return Credentials.from_authorized_user_info(info)


def ensure_fresh(creds: Credentials) -> bool:
    """Refresh the access token if expired. Returns True if it was refreshed.

    Raises if the refresh token is dead (Testing-mode 7-day expiry) — the caller
    turns that into a 'reconnect' response rather than crashing.
    """
    if creds.valid:
        return False
    if not creds.refresh_token:
        raise RuntimeError("no refresh token; reconnect required")
    creds.refresh(Request())
    return True


def _service(creds: Credentials):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _gmail(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def send_email(creds: Credentials, *, to: str, subject: str, body: str,
               thread_id: str | None = None) -> dict:
    """Send a plain-text email as the connected account. Returns {id, threadId}.

    If thread_id is given the message is threaded into that conversation (used
    for follow-ups). reply-to is the sending account itself so candidate replies
    come back to the agent mailbox.
    """
    import base64
    from email.mime.text import MIMEText

    msg = MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    sent = _gmail(creds).users().messages().send(userId="me", body=payload).execute()
    return {"id": sent["id"], "thread_id": sent["threadId"]}


def read_latest_reply(creds: Credentials, thread_id: str, self_email: str) -> dict | None:
    """Return the newest inbound message in a thread (not sent by us).

    {from, date, body} or None if the only messages are our own outreach.
    """
    import base64

    svc = _gmail(creds)
    thread = svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
    messages = thread.get("messages", [])
    for msg in reversed(messages):  # newest first
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        sender = headers.get("from", "")
        if self_email.lower() in sender.lower():
            continue  # skip our own outreach
        return {
            "from": sender,
            "date": headers.get("date", ""),
            "body": _extract_body(msg["payload"], base64),
        }
    return None


def _extract_body(payload, base64) -> str:
    """Pull plain-text from a Gmail message payload (walks multipart)."""
    def decode(data: str) -> str:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")

    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return decode(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return decode(part["body"]["data"])
    for part in payload.get("parts", []) or []:
        got = _extract_body(part, base64)
        if got:
            return got
    return ""


def primary_email(creds: Credentials) -> str:
    """The primary calendar's id is the account's email address."""
    return _service(creds).calendarList().get(calendarId="primary").execute()["id"]


def free_busy(creds: Credentials, calendar_id: str, time_min: str, time_max: str) -> list[dict]:
    body = {"timeMin": time_min, "timeMax": time_max, "items": [{"id": calendar_id}]}
    resp = _service(creds).freebusy().query(body=body).execute()
    cal = resp["calendars"][calendar_id]
    if cal.get("errors"):
        # Per research: a per-calendar error means "unknown", never "free".
        raise RuntimeError(f"FreeBusy error for {calendar_id}: {cal['errors']}")
    return cal.get("busy", [])