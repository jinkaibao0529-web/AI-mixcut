from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.paths import ensure_data_dirs
from app.services.material_store import init_db
from app.services.workspace_store import init_workspace_db

app = FastAPI(title="AI Video Editor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "null",
    ],
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.on_event("startup")
def startup() -> None:
    ensure_data_dirs()
    init_db()
    init_workspace_db()


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": "ai-video-editor"}
