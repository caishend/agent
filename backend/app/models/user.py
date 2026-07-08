from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db import Base

class User(Base):
    __tablename__ = "user"

    user_id     = Column(Integer, primary_key=True, index=True)
    username    = Column(String(50), unique=True, nullable=False)
    email       = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    create_time = Column(DateTime, default=datetime.utcnow)

    tasks = relationship("Task", back_populates="user")
