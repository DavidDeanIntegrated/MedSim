"""Authentication routes: register, login, profile."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session as DBSession

from app.auth.dependencies import get_current_user
from app.auth.security import create_access_token, hash_password, verify_password
from app.db.engine import get_db
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1)
    role: str = "learner"
    institution: str | None = None
    specialty: str | None = None
    training_level: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    display_name: str


class UserProfile(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    institution: str | None
    specialty: str | None
    training_level: str | None


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, db: DBSession = Depends(get_db)) -> dict[str, Any]:
    existing = db.query(User).filter(User.email == request.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    if request.role not in ("learner", "faculty"):
        raise HTTPException(status_code=400, detail="Can only self-register as learner or faculty")

    user = User(
        email=request.email,
        hashed_password=hash_password(request.password),
        display_name=request.display_name,
        role=request.role,
        institution=request.institution,
        specialty=request.specialty,
        training_level=request.training_level,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.id, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "role": user.role,
        "display_name": user.display_name,
    }


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: DBSession = Depends(get_db)) -> dict[str, Any]:
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    token = create_access_token({"sub": user.id, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "role": user.role,
        "display_name": user.display_name,
    }


@router.get("/me", response_model=UserProfile)
def get_profile(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "institution": user.institution,
        "specialty": user.specialty,
        "training_level": user.training_level,
    }
