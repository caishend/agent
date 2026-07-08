from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db import Base

class Conversation(Base):
    __tablename__ = "conversation"

    conv_id    = Column(Integer, primary_key=True, index=True)
    task_id    = Column(Integer, ForeignKey("task.task_id"), nullable=False)
    role       = Column(Enum("user", "assistant", "tool"), nullable=False)
    content    = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="conversations")


class Document(Base):
    __tablename__ = "document"

    doc_id      = Column(Integer, primary_key=True, index=True)
    task_id     = Column(Integer, ForeignKey("task.task_id"), nullable=False)
    filename    = Column(String(255), nullable=False)
    file_type   = Column(String(20))
    file_path   = Column(String(500), nullable=False)
    upload_time = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="documents")
