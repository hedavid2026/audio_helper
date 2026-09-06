from fastapi import APIRouter

from api import new_request_id
from schemas import HealthData, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(
        request_id=new_request_id(),
        data=HealthData(status="ok"),
    )
