from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "services": {
            "parser": "ok",
            "engine": "ok",
            "voice": "ok",
            "database": "ok",
        },
    }
