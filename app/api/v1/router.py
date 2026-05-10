from fastapi import APIRouter

from app.api.v1.endpoints.action_types import router as action_types_router
from app.api.v1.endpoints.agent import router as agent_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.notes import router as notes_router
from app.api.v1.endpoints.plants import router as plants_router
from app.api.v1.endpoints.profile import router as profile_router
from app.api.v1.endpoints.schedules import router as schedules_router
from app.api.v1.endpoints.sync import router as sync_router
from app.api.v1.endpoints.task_completions import router as task_completions_router
from app.api.v1.endpoints.timelines import router as timelines_router
from app.api.v1.endpoints.uploads import router as uploads_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(agent_router)
api_router.include_router(plants_router)
api_router.include_router(action_types_router)
api_router.include_router(schedules_router)
api_router.include_router(task_completions_router)
api_router.include_router(notes_router)
api_router.include_router(timelines_router)
api_router.include_router(profile_router)
api_router.include_router(sync_router, prefix="/sync")
api_router.include_router(uploads_router)
