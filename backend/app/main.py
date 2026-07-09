from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api import agent, auth, chat, documents, tasks
from app.db import Base, engine

Base.metadata.create_all(bind=engine)

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


@app.get("/")
def root():
    return {"message": "SkyGuard API is running"}
