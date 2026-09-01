import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api import admin, admin_pages, careers, chat, leads
from app.config import get_settings
from app.database import engine
from app.main_state import limiter
from app.schemas import StatusResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Company Document Chatbot", version="1.0.0", docs_url="/api/docs", redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}))
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-Admin-API-Key"],
)
app.include_router(chat.router)
app.include_router(leads.router)
app.include_router(careers.router)
app.include_router(admin.router)
app.include_router(admin_pages.router)


@app.get("/health", response_model=StatusResponse, tags=["system"])
def health() -> StatusResponse:
    return StatusResponse(status="ok")


@app.get("/ready", response_model=StatusResponse, tags=["system"])
def ready() -> StatusResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not ready"})
    try:
        settings.validate_ai_provider()
    except ValueError:
        return JSONResponse(status_code=503, content={"status": "not ready"})
    return StatusResponse(status="ready")


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    # Do not log exception values: database errors can include bound lead fields.
    logger.error("Unhandled %s at %s", type(exc).__name__, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "An internal error occurred"})


static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
