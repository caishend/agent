from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db import Base

class Task(Base):
    __tablename__ = "task"

    task_id      = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("user.user_id"), nullable=False)
    task_name    = Column(String(100), nullable=False)
    disaster_type = Column(String(50))
    location     = Column(String(100))
    status       = Column(Enum("IDLE", "RUNNING", "DONE", "ERROR"), default="IDLE")
    create_time  = Column(DateTime, default=datetime.utcnow)

    user          = relationship("User", back_populates="tasks")
    conversations = relationship("Conversation", back_populates="task")
    documents     = relationship("Document", back_populates="task")
