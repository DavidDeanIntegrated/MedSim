"""FastAPI dependencies for JWT authentication."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DBSession

from app.auth.security import decode_access_token
from app.db.engine import get_db
from app.db.models import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DBSession = Depends(get_db),
) -> User:
    """Extract and validate the current user from the JWT bearer token.

    If no token is provided, returns a default demo user (for backwards compat).
    """
    if credentials is None:
        # Allow unauthenticated access for demo / local development
        demo = db.query(User).filter(User.email == "demo@medsim.local").first()
        if demo is None:
            from app.auth.security import hash_password

            demo = User(
                email="demo@medsim.local",
                hashed_password=hash_password("demo"),
                display_name="Demo User",
                role="learner",
            )
            db.add(demo)
            db.commit()
            db.refresh(demo)
        return demo

    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


def require_role(*roles: str):
    """Dependency factory: require user to have one of the given roles."""

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' not authorized. Required: {', '.join(roles)}",
            )
        return user

    return _check
