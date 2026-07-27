import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.api import admin, auth, chat, integrations, mail, resources
from app.core.config import get_settings
from app.core.responses import ApiError, api_error_handler, http_error_handler, validation_error_handler
from app.db.session import engine, redis_client

settings = get_settings()
ROUTERS = [auth.router, resources.conversations, resources.messages, resources.feedbacks, chat.router, mail.router, integrations.router, integrations.eval_router, admin.router]


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await engine.dispose()
    await redis_client.aclose()


app = FastAPI(title="Chatbot Law Core API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.fe_domain], allow_credentials=True, allow_methods=["GET", "HEAD", "PUT", "PATCH", "POST", "DELETE"], allow_headers=["Content-Type", "Authorization"])
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.oauth_session_secret,
    session_cookie="core_oauth_session",
    max_age=600,
    same_site="lax",
    https_only=settings.is_production,
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Response-Time-Ms"] = str(round((time.perf_counter() - started) * 1000))
    return response


@app.get("/healthz", include_in_schema=False)
async def healthz():
    database, redis, ai = "healthy", "healthy", "healthy"
    try:
        async with engine.connect() as connection: await connection.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception: database = "unhealthy"
    try: await redis_client.ping()
    except Exception: redis = "unhealthy"
    try:
        async with httpx.AsyncClient(timeout=3) as client: (await client.get(settings.ai_base_url + "/health")).raise_for_status()
    except Exception: ai = "unhealthy"
    status = 200 if all(item == "healthy" for item in (database, redis, ai)) else 503
    return JSONResponse(status_code=status, content={"status": "healthy" if status == 200 else "degraded", "database": database, "redis": redis, "ai": ai})


for router in ROUTERS:
    app.include_router(router)
    app.include_router(router, prefix="/api/v1", include_in_schema=False)
