import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.task import Task
from app.models.conversation import Document
from app.utils import get_current_user_id
from app.config import settings

router = APIRouter()


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
FILE_TYPE_BY_EXTENSION = {
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".txt": "TXT",
    **{extension: "IMAGE" for extension in IMAGE_EXTENSIONS},
}


@router.get("/{task_id}/documents")
def list_documents(task_id: int,
                   user_id: int = Depends(get_current_user_id),
                   db: Session = Depends(get_db)):
    _get_task_or_404(task_id, user_id, db)
    documents = (
        db.query(Document)
        .filter(Document.task_id == task_id)
        .order_by(Document.upload_time.desc(), Document.doc_id.desc())
        .all()
    )
    return [_document_payload(document) for document in documents]


@router.post("/{task_id}/upload")
async def upload_file(task_id: int, file: UploadFile = File(...),
                      user_id: int = Depends(get_current_user_id),
                      db: Session = Depends(get_db)):
    _get_task_or_404(task_id, user_id, db)

    save_dir = os.path.join(settings.UPLOAD_DIR, str(task_id))
    os.makedirs(save_dir, exist_ok=True)
    filename = _safe_filename(file.filename)
    save_path = _unique_path(Path(save_dir), filename)

    with open(save_path, "wb") as f:
        f.write(await file.read())

    ext = save_path.suffix.lower()
    file_type = FILE_TYPE_BY_EXTENSION.get(ext, "OTHER")

    doc = Document(task_id=task_id, filename=save_path.name,
                   file_type=file_type, file_path=str(save_path))
    db.add(doc)
    db.commit()
    db.refresh(doc)
    payload = _document_payload(doc)
    payload["mime_type"] = file.content_type
    payload["status"] = "uploaded"
    return payload


def _get_task_or_404(task_id: int, user_id: int, db: Session) -> Task:
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "upload.bin").name.strip()
    return name or "upload.bin"


def _unique_path(directory: Path, filename: str) -> Path:
    target = directory / filename
    if not target.exists():
        return target
    stem = target.stem or "upload"
    suffix = target.suffix
    return directory / f"{stem}_{uuid4().hex[:8]}{suffix}"


def _document_payload(doc: Document) -> dict:
    ext = Path(doc.filename).suffix.lower()
    file_type = doc.file_type or FILE_TYPE_BY_EXTENSION.get(ext, "OTHER")
    payload = {
        "doc_id": doc.doc_id,
        "filename": doc.filename,
        "file_type": file_type,
        "file_path": doc.file_path,
        "upload_time": doc.upload_time.isoformat() if doc.upload_time else None,
    }
    preview_url = _preview_url(doc.file_path)
    if preview_url:
        payload["preview_url"] = preview_url
    return {
        **payload,
    }


def _preview_url(file_path: str) -> str | None:
    normalized = str(file_path or "").replace("\\", "/")
    marker = "data/uploads/"
    if marker not in normalized:
        return None
    return "/artifacts/uploads/" + normalized.split(marker, 1)[1]
