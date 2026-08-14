from fastapi import APIRouter

from app.api.v1 import audits, auth, frameworks, notifications, organizations, privacy

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(frameworks.router)
api_router.include_router(audits.router)
api_router.include_router(notifications.router)
api_router.include_router(privacy.router)
