from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Neon: POOLED url for the app (hostname has -pooler), DIRECT url for migrations.
    DATABASE_URL: str = "postgresql+asyncpg://scheduling:scheduling_dev@localhost:5432/scheduling"
    DATABASE_URL_DIRECT: str = "postgresql://scheduling:scheduling_dev@localhost:5432/scheduling"

    # LLM: only used to parse the recruiter's plain-English into a parameter card.
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"

    # Google OAuth (Testing mode). Secrets live in Railway, never the frontend.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "https://rarproto-production.up.railway.app/auth/google/callback"

    # Scope set is fixed from day one (declared even though Phase 1 only reads FreeBusy).
    GOOGLE_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]

    # CORS: comma-separated exact origins; regex for Vercel previews.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    CORS_ORIGIN_REGEX: str = r"https://.*\.vercel\.app"

   

    # Where the OAuth callback sends the browser back to.
    FRONTEND_URL: str = "http://localhost:5173"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
