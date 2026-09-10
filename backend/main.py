from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings

app = FastAPI(title="Scheduling Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.auth import router as auth_router  # noqa: E402
from api.availability import router as availability_router  # noqa: E402
from api.jobs import router as jobs_router  # noqa: E402
from api.slots import router as slots_router  # noqa: E402
from api.outreach import router as outreach_router  # noqa: E402
from api.replies import router as replies_router  # noqa: E402
from api.board import router as board_router
from api.reoffer import router as reoffer_router  # noqa: E402

app.include_router(auth_router)
app.include_router(availability_router)
app.include_router(jobs_router)
app.include_router(slots_router)
app.include_router(outreach_router)
app.include_router(replies_router)
app.include_router(board_router)
app.include_router(reoffer_router)

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}