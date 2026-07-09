import os
import json
import threading
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.agent.tools.base_tool import ToolInput
from app.agent.tools.document import DocumentTool
from app.agent.runtime import session_store
from app.db import SessionLocal, get_db
from app.models.task import Task
from app.models.conversation import Conversation, Document
from app.models.overview import KnowledgeGraphEntity, KnowledgeGraphRelation
from app.services.graphrag_ingest import build_graph_payload, clear_task_graph_from_neo4j, write_payload_to_neo4j
from app.utils import get_current_user_id
from app.config import settings

router = APIRouter()

FILE_TYPE_BY_EXTENSION = {
    ".pdf": "PDF",
    ".doc": "DOC",
    ".docx": "DOCX",
    ".txt": "TXT",
    ".md": "MD",
    ".csv": "CSV",
    ".xls": "XLS",
    ".xlsx": "XLSX",
    ".png": "IMAGE",
    ".jpg": "IMAGE",
    ".jpeg": "IMAGE",
    ".webp": "IMAGE",
    ".gif": "IMAGE",
    ".bmp": "IMAGE",
    ".tif": "IMAGE",
    ".tiff": "IMAGE",
}

GRAPH_DOCUMENT_TYPES = {"PDF", "DOC", "DOCX", "TXT", "MD", "CSV", "XLS", "XLSX"}


class DeleteDocumentPathIn(BaseModel):
    file_path: str


class DeleteArtifactIn(BaseModel):
    path: str


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
    rows = [row for row in rows if _is_graph_source_document(row, task_id)]
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
async def upload_file(task_id: int,
                      file: UploadFile = File(...),
                      user_id: int = Depends(get_current_user_id),
                      db: Session = Depends(get_db)):
    task = _get_task_or_404(task_id, user_id, db)
    save_path, file_type = await _save_uploaded_file(task_id, file)

    doc = Document(task_id=task_id, filename=save_path.name,
                   file_type=file_type, file_path=str(save_path))
    db.add(doc)
    db.commit()
    db.refresh(doc)
    payload = _document_payload(doc)
    payload["mime_type"] = file.content_type
    payload["status"] = "uploaded"
    if file_type != "IMAGE":
        _schedule_task_knowledge_graph_rebuild(task.task_id)
    return payload


@router.post("/{task_id}/upload-temp")
async def upload_temp_file(task_id: int, file: UploadFile = File(...),
                           user_id: int = Depends(get_current_user_id),
                           db: Session = Depends(get_db)):
    _get_task_or_404(task_id, user_id, db)
    save_path, file_type = await _save_uploaded_file(task_id, file, temporary=True)
    if file_type != "IMAGE":
        _delete_file_if_local(str(save_path))
        raise HTTPException(400, "图像识别只能上传图片文件")
    return {
        "doc_id": None,
        "filename": save_path.name,
        "file_type": file_type,
        "file_path": str(save_path),
        "mime_type": file.content_type,
        "status": "temporary",
    }


def _get_task_or_404(task_id: int, user_id: int, db: Session) -> Task:
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


async def _save_uploaded_file(task_id: int, file: UploadFile, temporary: bool = False) -> tuple[Path, str]:
    save_dir = Path(settings.UPLOAD_DIR) / str(task_id)
    if temporary:
        save_dir = save_dir / "_temp"
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(file.filename)
    save_path = _unique_path(save_dir, filename)

    with open(save_path, "wb") as f:
        f.write(await file.read())

    ext = save_path.suffix.lower()
    file_type = FILE_TYPE_BY_EXTENSION.get(ext, "OTHER")
    return save_path, file_type


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
    return payload


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
    _schedule_task_knowledge_graph_rebuild(task_id)


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
    _schedule_task_knowledge_graph_rebuild(task_id)


@router.post("/{task_id}/artifacts/delete", status_code=204)
def delete_artifact(task_id: int,
                    data: DeleteArtifactIn,
                    user_id: int = Depends(get_current_user_id),
                    db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")

    artifact_path = _normalize_path(data.path)
    if not artifact_path:
        raise HTTPException(400, "产物路径不能为空")

    _delete_artifact_document_rows(db, task_id, artifact_path)
    _remove_artifact_from_session(task_id, artifact_path)
    _remove_artifact_from_trace_records(db, task_id, artifact_path)
    _delete_file_if_local(artifact_path)


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
    db.commit()


def _clear_task_knowledge_graph(db: Session, task_id: int) -> None:
    db.query(KnowledgeGraphRelation).filter(KnowledgeGraphRelation.task_id == task_id).delete(synchronize_session=False)
    db.query(KnowledgeGraphEntity).filter(KnowledgeGraphEntity.task_id == task_id).delete(synchronize_session=False)
    db.commit()
    metadata = session_store.metadata_for(task_id)
    metadata["neo4j_clear_status"] = clear_task_graph_from_neo4j(task_id)


def _rebuild_task_knowledge_graph(db: Session, task: Task) -> None:
    _clear_task_knowledge_graph(db, task.task_id)
    rows = db.query(Document).filter(Document.task_id == task.task_id).all()
    files = [
        {"path": row.file_path, "name": row.filename, "filename": row.filename, "type": row.file_type}
        for row in rows
        if _is_graph_source_document(row, task.task_id)
    ]

    metadata = session_store.metadata_for(task.task_id)
    if not files:
        metadata.pop("documents", None)
        metadata.pop("knowledge_graph", None)
        metadata.pop("neo4j_ingest_status", None)
        return

    document_result = DocumentTool().run(
        tool_input=ToolInput(query=task.task_name or "", files=files, params={}),
        context=None,
    )
    documents = document_result.data.get("documents") or []
    metadata["documents"] = documents
    payload = build_graph_payload(
        task_id=task.task_id,
        task_name=task.task_name,
        metadata={"documents": documents},
        query=task.task_name or "",
        use_llm=False,
    )
    metadata["knowledge_graph"] = payload
    metadata["neo4j_ingest_status"] = write_payload_to_neo4j(payload)
    _upsert_knowledge_graph_payload(db, task.task_id, payload)


def _schedule_task_knowledge_graph_rebuild(task_id: int) -> None:
    thread = threading.Thread(
        target=_rebuild_task_knowledge_graph_for_task_id,
        args=(task_id,),
        daemon=True,
        name=f"kg-rebuild-task-{task_id}",
    )
    thread.start()


def _rebuild_task_knowledge_graph_for_task_id(task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.task_id == task_id).first()
        if task:
            _rebuild_task_knowledge_graph(db, task)
    except Exception as error:
        metadata = session_store.metadata_for(task_id)
        metadata["knowledge_graph_rebuild_status"] = {
            "status": "failed",
            "reason": str(error),
        }
    finally:
        db.close()


def _upsert_knowledge_graph_payload(db: Session, task_id: int, payload: dict) -> None:
    for item in payload.get("entities", []):
        name = str(item.get("name") or "").strip()
        entity_type = str(item.get("entity_type") or "概念").strip()
        if not name:
            continue
        db.add(
            KnowledgeGraphEntity(
                task_id=task_id,
                name=name,
                entity_type=entity_type,
                description=str(item.get("description") or "")[:1000],
                source_type=str(item.get("source_type") or "document")[:50],
                source_ref=str(item.get("source_ref") or "")[:500] or None,
                confidence=float(item.get("confidence") or 0.7),
            )
        )
    for item in payload.get("relations", []):
        source_name = str(item.get("source_name") or "").strip()
        target_name = str(item.get("target_name") or "").strip()
        if not source_name or not target_name:
            continue
        db.add(
            KnowledgeGraphRelation(
                task_id=task_id,
                source_name=source_name,
                source_type=str(item.get("source_type") or "概念")[:50],
                target_name=target_name,
                target_type=str(item.get("target_type") or "概念")[:50],
                relation_type=str(item.get("relation_type") or "相关")[:100],
                evidence=str(item.get("evidence") or "")[:2000],
                source_ref=str(item.get("source_ref") or "")[:500] or None,
                confidence=float(item.get("confidence") or 0.7),
            )
        )
    db.commit()


def _remove_document_from_session(task_id: int, file_path: str, filename: str) -> None:
    metadata = session_store.metadata_for(task_id)
    documents = metadata.get("documents") or []
    metadata["documents"] = [
        item for item in documents
        if not isinstance(item, dict)
        or (item.get("source") != filename and item.get("source") != file_path and item.get("metadata", {}).get("path") != file_path)
    ]


def _delete_artifact_document_rows(db: Session, task_id: int, artifact_path: str) -> None:
    refs = _artifact_related_paths(artifact_path)
    rows = db.query(Document).filter(Document.task_id == task_id).all()
    changed = False
    for row in rows:
        if _normalize_path(row.file_path) in refs:
            db.delete(row)
            changed = True
    if changed:
        db.commit()


def _remove_artifact_from_session(task_id: int, artifact_path: str) -> None:
    metadata = session_store.metadata_for(task_id)
    refs = _artifact_related_paths(artifact_path)
    artifacts = metadata.get("artifacts") or []
    metadata["artifacts"] = [
        item for item in artifacts
        if not isinstance(item, dict) or _normalize_path(item.get("path")) not in refs
    ]
    if _normalize_path(metadata.get("last_report_path")) in refs:
        metadata.pop("last_report_path", None)


def _remove_artifact_from_trace_records(db: Session, task_id: int, artifact_path: str) -> None:
    refs = _artifact_related_paths(artifact_path)
    rows = (
        db.query(Conversation)
        .filter(Conversation.task_id == task_id, Conversation.role == "tool")
        .all()
    )
    changed = False
    for row in rows:
        try:
            payload = json.loads(row.content or "{}")
        except json.JSONDecodeError:
            continue
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        filtered = [
            artifact for artifact in artifacts
            if not isinstance(artifact, dict) or _normalize_path(artifact.get("path")) not in refs
        ]
        if len(filtered) == len(artifacts):
            continue
        payload["artifacts"] = filtered
        row.content = json.dumps(payload, ensure_ascii=False, default=str)
        db.add(row)
        changed = True
    if changed:
        db.commit()


def _artifact_related_paths(path: str) -> set[str]:
    normalized = _normalize_path(path)
    refs = {normalized}
    suffix = Path(normalized).suffix.lower()
    if suffix:
        base = normalized[: -len(suffix)]
        refs.add(base + ".json")
        refs.add(base + ".docx")
        refs.add(base + ".pdf")
    return refs


def _normalize_path(path: str | None) -> str:
    return str(path or "").replace("\\", "/").strip()


def _is_graph_source_document(row: Document, task_id: int) -> bool:
    file_type = str(row.file_type or "").upper()
    path = _normalize_path(row.file_path)
    upload_prefix = _normalize_path(str(Path(settings.UPLOAD_DIR) / str(task_id))) + "/"
    return bool(path) and file_type in GRAPH_DOCUMENT_TYPES and path.startswith(upload_prefix) and "/_temp/" not in path


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
