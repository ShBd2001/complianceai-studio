from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.rate_limit import limiter
from app.services.scheduler import scheduler_loop

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s :: %(message)s",
)
logger = logging.getLogger("complianceai")

# Routes de documentation interactive : elles ont besoin de charger des
# ressources externes, contrairement au reste de l'API.
DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Demarrage de %s (env=%s)", settings.APP_NAME, settings.ENV)
    if settings.is_production and settings.JWT_SECRET in {"CHANGE_ME", ""}:
        raise RuntimeError("JWT_SECRET non configure en production.")

    scheduler_task: asyncio.Task | None = None
    if settings.SCHEDULER_ENABLED:
        scheduler_task = asyncio.create_task(scheduler_loop())

    yield

    if scheduler_task is not None:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task

    logger.info("Arret de %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="Plateforme SaaS d'audit de conformite reglementaire (RGPD, NIS2, ISO 27001).",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

if settings.is_production:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*.onrender.com", "*.up.railway.app"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,          # necessaire pour le cookie de refresh
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """En-tetes de securite (ref. CC1.2 / OWASP Secure Headers)."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    started = time.perf_counter()

    response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cache-Control"] = "no-store"

    # La politique stricte convient aux reponses JSON de l'API, mais elle
    # empecherait Swagger UI de charger ses ressources : la page s'afficherait
    # vide. Les routes de documentation recoivent donc une politique dediee,
    # limitee au CDN dont FastAPI depend.
    if request.url.path in DOCS_PATHS:
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "img-src 'self' https://fastapi.tiangolo.com data:; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    elapsed = (time.perf_counter() - started) * 1000
    logger.info(
        "%s %s -> %s (%.1f ms) [%s]",
        request.method, request.url.path, response.status_code, elapsed, request_id,
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Messages de validation lisibles, sans fuite de structure interne."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Donnees invalides.",
            "errors": [
                {"champ": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
                for e in exc.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Erreur non geree sur %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Une erreur interne est survenue."},
    )


@app.get("/health", tags=["Systeme"])
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.ENV}


app.include_router(api_router)
