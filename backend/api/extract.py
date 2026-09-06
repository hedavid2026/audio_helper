import logging

from fastapi import APIRouter

from api import new_request_id
from schemas import AppError, ExtractRequest, ExtractResponse
from services.deepseek_extract import extract_meetup_info

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extract"])


@router.post(
    "/extract",
    response_model=ExtractResponse,
    responses={
        422: {"description": "Incomplete meetup info or invalid request"},
        502: {"description": "Model/upstream error"},
        504: {"description": "Extract timeout"},
    },
)
async def extract_addresses(body: ExtractRequest) -> ExtractResponse:
    request_id = new_request_id()
    text = body.text.strip()
    city = (body.city or "").strip() or "杭州"
    if not text:
        raise AppError(
            status_code=422,
            code="MISSING_FIELD",
            message="请提供识别出的用户原话 text。",
            stage="extract",
            request_id=request_id,
        )

    data = await extract_meetup_info(text=text, page_city=city, request_id=request_id)
    logger.info(
        "extract_endpoint_ok request_id=%s category=%s",
        request_id,
        data.category,
    )
    return ExtractResponse(request_id=request_id, data=data)
