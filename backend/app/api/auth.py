from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db import get_db
from app.models.user import User
from app.utils import hash_password, verify_password, create_token, get_current_user_id

router = APIRouter()

class RegisterIn(BaseModel):
    username: str
    email: str
    password: str

class LoginIn(BaseModel):
    username: str
    password: str


def _user_payload(user: User) -> dict:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "create_time": user.create_time.isoformat() if user.create_time else None,
    }

@router.post("/register", status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "用户名已存在")
    user = User(username=data.username, email=data.email,
                password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    return {"message": "注册成功"}

@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    return {"access_token": create_token(user.user_id), "token_type": "bearer", "user": _user_payload(user)}


@router.get("/me")
def current_user(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    return _user_payload(user)
