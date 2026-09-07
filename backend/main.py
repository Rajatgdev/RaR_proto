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

from api.ping import router as ping_router  # noqa: E402
from api.auth import router as auth_router  # noqa: E402
from api.availability import router as availability_router  # noqa: E402

app.include_router(ping_router)
app.include_router(auth_router)
app.include_router(availability_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}