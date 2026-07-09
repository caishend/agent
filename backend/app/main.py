from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import threading

from app.api import agent, auth, chat, documents, overview, tasks
from app.config import settings
from app.db import Base, engine
import app.models  # noqa: F401

Base.metadata.create_all(bind=engine)


def ensure_runtime_schema() -> None:
    if engine.dialect.name != "mysql":
        return
    for statement in (
        "ALTER TABLE conversation MODIFY role ENUM('user','assistant','tool') NOT NULL",
        "ALTER TABLE conversation MODIFY content LONGTEXT NOT NULL",
    ):
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except Exception:
            pass


ensure_runtime_schema()

app = FastAPI(title="SkyGuard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["任务"])
app.include_router(chat.router, prefix="/api/tasks", tags=["对话"])
app.include_router(documents.router, prefix="/api/tasks", tags=["文件"])
app.include_router(agent.router, prefix="/api/tasks", tags=["Agent"])
Path("data/screenshots").mkdir(parents=True, exist_ok=True)
Path("data/reports").mkdir(parents=True, exist_ok=True)
Path("data/remote_sensing").mkdir(parents=True, exist_ok=True)
Path("data/uploads").mkdir(parents=True, exist_ok=True)
app.mount("/artifacts/screenshots", StaticFiles(directory="data/screenshots"), name="screenshots")
app.mount("/artifacts/reports", StaticFiles(directory="data/reports"), name="reports")
app.mount("/artifacts/remote-sensing", StaticFiles(directory="data/remote_sensing"), name="remote_sensing")
app.mount("/artifacts/uploads", StaticFiles(directory="data/uploads"), name="uploads")
app.include_router(overview.router, prefix="/api/overview", tags=["Overview"])


@app.get("/")
def root():
    return {"message": "SkyGuard API is running"}


@app.on_event("startup")
def warm_disaster_model() -> None:
    if not settings.DISASTER_MODEL_ENABLED or not settings.DISASTER_MODEL_WARMUP:
        return
    thread = threading.Thread(target=_warm_disaster_model_worker, daemon=True, name="disaster-model-warmup")
    thread.start()


def _warm_disaster_model_worker() -> None:
    try:
        from app.agent.tools.disaster_detector import DisasterPipelineDetector

        detector = DisasterPipelineDetector(
            model_dir=settings.DISASTER_MODEL_DIR,
            device=settings.DISASTER_MODEL_DEVICE,
            gate_threshold=settings.DISASTER_GATE_THRESHOLD,
        )
        detector.preload()
        print("[SkyGuard] disaster model warmed and cached.")
    except Exception as error:
        print(f"[SkyGuard] disaster model warmup skipped: {error}")
