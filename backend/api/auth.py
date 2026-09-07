from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import gcal
from config import settings
from db.session import get_session

router = APIRouter(prefix="/auth/google", tags=["auth"])

_SECURE = settings.GOOGLE_REDIRECT_URI.startswith("https")


@router.get("/login")
async def login():
    """Start OAuth. Top-level redirect to Google; state stored in a cookie."""
    flow = gcal.build_flow()
    url, state = flow.authorization_url(
        access_type="offline",       # get a refresh token
        include_granted_scopes="true",
        prompt="consent",            # force refresh token on re-consent
    )

    resp = RedirectResponse(url)
    resp.set_cookie(
        "oauth_state", state, max_age=600, httponly=True,
        secure=_SECURE, samesite="lax",
    )
    # google-auth-oauthlib uses PKCE: the callback must present the same
    # code_verifier that generated this request. Stash it (short-lived cookie).
    resp.set_cookie(
        "oauth_verifier", flow.code_verifier, max_age=600, httponly=True,
        secure=_SECURE, samesite="lax",
    )
    return resp

@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_session)):
    error = request.query_params.get("error")
    if error:
        raise HTTPException(400, f"Google returned: {error}")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(400, "missing code/state")
    if state != request.cookies.get("oauth_state"):
        raise HTTPException(400, "state mismatch")  # CSRF guard

    flow = gcal.build_flow(state=state)
    flow.code_verifier = request.cookies.get("oauth_verifier")
    await run_in_threadpool(flow.fetch_token, code=code)
    creds = flow.credentials

    email = await run_in_threadpool(gcal.primary_email, creds)
    await db.execute(
        text(
            "INSERT INTO google_account (email, credentials, updated_at) "
            "VALUES (:e, CAST(:c AS JSONB), now()) "
            "ON CONFLICT (email) DO UPDATE SET "
            "credentials = EXCLUDED.credentials, updated_at = now()"
        ),
        {"e": email, "c": creds.to_json()},
    )
    await db.commit()

    resp = RedirectResponse(f"{settings.FRONTEND_URL}/?connected=1")
    resp.delete_cookie("oauth_state")
    resp.delete_cookie("oauth_verifier")
    return resp


@router.get("/status")
async def status(db: AsyncSession = Depends(get_session)):
    row = (
        await db.execute(
            text("SELECT email FROM google_account ORDER BY updated_at DESC LIMIT 1")
        )
    ).mappings().one_or_none()
    return {"connected": row is not None, "email": row["email"] if row else None}