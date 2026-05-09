import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging


configure_logging(settings.log_level)
logger = logging.getLogger("app.main")

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)

os.makedirs(str(settings.upload_dir_path), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir_path)), name="uploads")

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id_header = request.headers.get("X-Request-ID")
    operation_id_header = request.headers.get("X-Operation-ID")
    request_id = request_id_header.strip() if request_id_header and request_id_header.strip() else str(uuid.uuid4())
    operation_id = operation_id_header.strip() if operation_id_header and operation_id_header.strip() else None
    if operation_id is None and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        operation_id = str(uuid.uuid4())

    request.state.request_id = request_id
    request.state.operation_id = operation_id

    started_at = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    if operation_id:
        response.headers["X-Operation-ID"] = operation_id
    logger.info(
        "request_complete",
        extra={
            "request_id": request_id,
            "operation_id": operation_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


app.include_router(api_router, prefix=settings.api_v1_prefix)
