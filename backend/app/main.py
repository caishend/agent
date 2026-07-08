from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, tasks, chat, documents
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

app.include_router(auth.router,      prefix="/api/auth",      tags=["认证"])
app.include_router(tasks.router,     prefix="/api/tasks",     tags=["任务"])
app.include_router(chat.router,      prefix="/api/tasks",     tags=["对话"])
app.include_router(documents.router, prefix="/api/tasks",     tags=["文件"])

@app.get("/")
def root():
    return {"message": "SkyGuard API is running"}
