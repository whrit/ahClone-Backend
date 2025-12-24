from fastapi import APIRouter

from app.api.routes import ads, audits, gsc, integrations, items, jobs, links, login, private, projects, serp, traffic, users, utils
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(projects.router)
api_router.include_router(jobs.router)
api_router.include_router(audits.router)
api_router.include_router(integrations.router)
api_router.include_router(gsc.router)
api_router.include_router(serp.router)
api_router.include_router(links.router)
api_router.include_router(traffic.router)
api_router.include_router(ads.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
