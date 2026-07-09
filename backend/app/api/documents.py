import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.agent.runtime import session_store
from app.db import get_db
from app.models.task import Task
from app.models.conversation import Document
from app.models.overview import KnowledgeGraphEntity, KnowledgeGraphRelation
from app.utils import get_current_user_id
from app.config import settings

router = APIRouter()


class DeleteDocumentPathIn(BaseModel):
    file_path: str


@router.get("/{task_id}/documents")
def list_documents(task_id: int,
                   user_id: int = Depends(get_current_user_id),
                   db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    rows = (
        db.query(Document)
        .filter(Document.task_id == task_id)
        .order_by(Document.upload_time.desc(), Document.doc_id.desc())
        .all()
    )
    return [
        {
            "doc_id": row.doc_id,
            "filename": row.filename,
            "file_type": row.file_type,
            "file_path": row.file_path,
            "upload_time": row.upload_time.isoformat() if row.upload_time else None,
            "status": "uploaded",
        }
        for row in rows
    ]


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
        "status": "uploaded",
    }


@router.delete("/{task_id}/documents/{doc_id}", status_code=204)
def delete_document(task_id: int,
                    doc_id: int,
                    user_id: int = Depends(get_current_user_id),
                    db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    doc = db.query(Document).filter(Document.task_id == task_id, Document.doc_id == doc_id).first()
    if not doc:
        raise HTTPException(404, "文档不存在")

    file_path = doc.file_path
    filename = doc.filename
    _delete_index_references(db, task_id, file_path, filename)
    db.delete(doc)
    db.commit()
    _remove_document_from_session(task_id, file_path, filename)
    _delete_file_if_local(file_path)


@router.post("/{task_id}/documents/delete-path", status_code=204)
def delete_document_by_path(task_id: int,
                            data: DeleteDocumentPathIn,
                            user_id: int = Depends(get_current_user_id),
                            db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    doc = db.query(Document).filter(Document.task_id == task_id, Document.file_path == data.file_path).first()
    if doc:
        _delete_index_references(db, task_id, doc.file_path, doc.filename)
        db.delete(doc)
        db.commit()
        _remove_document_from_session(task_id, doc.file_path, doc.filename)
    else:
        _remove_document_from_session(task_id, data.file_path, Path(data.file_path).name)
    _delete_file_if_local(data.file_path)


def _delete_index_references(db: Session, task_id: int, file_path: str, filename: str) -> None:
    refs = {file_path, filename}
    db.query(KnowledgeGraphRelation).filter(
        KnowledgeGraphRelation.task_id == task_id,
        KnowledgeGraphRelation.source_ref.in_(refs),
    ).delete(synchronize_session=False)
    db.query(KnowledgeGraphEntity).filter(
        KnowledgeGraphEntity.task_id == task_id,
        KnowledgeGraphEntity.source_ref.in_(refs),
    ).delete(synchronize_session=False)


def _remove_document_from_session(task_id: int, file_path: str, filename: str) -> None:
    metadata = session_store.metadata_for(task_id)
    documents = metadata.get("documents") or []
    metadata["documents"] = [
        item for item in documents
        if not isinstance(item, dict)
        or (item.get("source") != filename and item.get("source") != file_path and item.get("metadata", {}).get("path") != file_path)
    ]


def _delete_file_if_local(file_path: str) -> None:
    try:
        path = Path(file_path).resolve()
        allowed_roots = [Path(settings.UPLOAD_DIR).resolve(), Path(settings.REPORT_DIR).resolve()]
        if any(path == root or root in path.parents for root in allowed_roots):
            path.unlink(missing_ok=True)
            metadata = path.with_suffix(".json")
            if metadata.exists() and any(root in metadata.resolve().parents or metadata.resolve() == root for root in allowed_roots):
                metadata.unlink(missing_ok=True)
    except OSError:
        pass
