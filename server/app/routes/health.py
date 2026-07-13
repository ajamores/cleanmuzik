"""Liveness probe (spec §6: GET /api/health → {"status": "ok"})."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
