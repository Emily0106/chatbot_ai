
# apps/backend/src/app/api/routes/metrics.py
from fastapi import APIRouter, Response
from app.core.metrics import REGISTRY, generate_latest, CONTENT_TYPE_LATEST

router = APIRouter()

@router.get("/metrics", include_in_schema=False)
def metrics():
    """
    Expose Prometheus metrics.
    No auth for now (handled by Gateway/Nginx).
    """
    data = generate_latest(REGISTRY)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
