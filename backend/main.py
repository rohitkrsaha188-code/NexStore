"""NexStore FastAPI application: initialization, routers, background workers."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import PROJECT_ROOT, settings
from backend.api.deps import get_node_manager
from backend.auth import init_auth_schema
from backend.database import db, log_activity, log_system_event, utcnow
from backend.exceptions import VaultError
from backend.logging_config import configure_logging
from backend.storage.node_manager import NodeManager
from backend.storage.object_store import ObjectStore

configure_logging()

DESCRIPTION = """
**NexStore** — fault-tolerant distributed object storage.

- Replicated uploads with least-utilized placement
- Automatic repair on node failure or corruption
- SHA-256 integrity verification
- Network partition & failure simulation
- Background rebalancing
"""

app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=None,
)


@app.on_event("startup")
async def on_startup() -> None:
    db.initialize()
    init_auth_schema()
    store = ObjectStore(settings.storage_root)
    manager = get_node_manager()
    manager.initialize_nodes()
    from backend.metadata.metadata_consistency import run_consistency_sweep

    run_consistency_sweep()
    _start_workers()
    with db.write() as conn:
        log_system_event(conn, "SYSTEM_START", "NexStore started; nodes ONLINE; workers running")


def _start_workers() -> None:
    from backend.workers.health_worker import health_worker_loop
    from backend.workers.integrity_worker import integrity_worker_loop
    from backend.workers.rebalance_worker import rebalance_worker_loop
    from backend.workers.repair_worker import repair_worker_loop

    app.state.worker_tasks = [
        asyncio.create_task(health_worker_loop(settings.health_check_interval)),
        asyncio.create_task(repair_worker_loop(settings.repair_interval)),
        asyncio.create_task(integrity_worker_loop(settings.integrity_check_interval)),
        asyncio.create_task(rebalance_worker_loop(settings.integrity_check_interval)),
    ]


@app.on_event("shutdown")
async def on_shutdown() -> None:
    for task in getattr(app.state, "worker_tasks", []):
        task.cancel()


# -- Error handling: structured JSON, never raw stack traces -------------------
@app.exception_handler(VaultError)
async def vault_error_handler(request: Request, exc: VaultError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "message": exc.message, "detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    import logging, traceback
    traceback.print_exc()

    logging.getLogger("vault.api").exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "An unexpected error occurred", "detail": str(exc)},
    )


# -- Routers -------------------------------------------------------------------
from backend.api.activity import router as activity_router  # noqa: E402
from backend.api.files import router as files_router  # noqa: E402
from backend.api.health import router as health_router  # noqa: E402
from backend.api.integrity import router as integrity_router  # noqa: E402
from backend.api.nodes import router as nodes_router  # noqa: E402
from backend.api.rebalance import router as rebalance_router  # noqa: E402
from backend.api.replicas import router as replicas_router  # noqa: E402
from backend.api.repairs import router as repairs_router  # noqa: E402
from backend.api.search import router as search_router  # noqa: E402
from backend.api.system import router as system_router  # noqa: E402
from backend.auth import router as auth_router  # noqa: E402
from backend.supabase_auth import router as supabase_auth_router  # noqa: E402

for router in (
    system_router, nodes_router, files_router, replicas_router,
    repairs_router, health_router, integrity_router,
    rebalance_router, activity_router, auth_router, supabase_auth_router, search_router,
):
    app.include_router(router)


# -- Root: serve the dashboard ---------------------------------------------------
@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "frontend" / "index.html")


app.mount(
    "/static",
    StaticFiles(directory=PROJECT_ROOT / "frontend"),
    name="static",
)
