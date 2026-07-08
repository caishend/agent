import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.task import Task
from app.models.conversation import Document
from app.utils import get_current_user_id
from app.config import settings

router = APIRouter()

@router.post("/{task_id}/upload")
async def upload_file(task_id: int, file: UploadFile = File(...),
                      user_id: int = Depends(get_current_user_id),
                      db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")

    save_dir = os.path.join(settings.UPLOAD_DIR, str(task_id))
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, file.filename)

    with open(save_path, "wb") as f:
        f.write(await file.read())

    ext = os.path.splitext(file.filename)[1].lower()
    file_type = {"pdf": "PDF", ".docx": "DOCX", ".txt": "TXT",
                 ".png": "IMAGE", ".jpg": "IMAGE", ".tif": "IMAGE"}.get(ext, "OTHER")

    doc = Document(task_id=task_id, filename=file.filename,
                   file_type=file_type, file_path=save_path)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"doc_id": doc.doc_id, "filename": doc.filename, "status": "uploaded"}
