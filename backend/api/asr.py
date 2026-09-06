import logging

from fastapi import APIRouter

from api import new_request_id
from schemas import AppError, AsrData, AsrRequest, AsrResponse
from services.audio_store import read_audio_bytes
from services.bailian_asr import transcribe_audio

logger = logging.getLogger(__name__)

router = APIRouter(tags=["asr"])


@router.post(
    "/asr",
    response_model=AsrResponse,
    responses={
        404: {"description": "audio_id not found or expired"},
        413: {"description": "Base64 payload too large"},
        422: {"description": "Empty transcript or invalid request"},
        502: {"description": "ASR upstream error"},
        504: {"description": "ASR timeout"},
    },
)
async def run_asr(body: AsrRequest) -> AsrResponse:
    request_id = new_request_id()
    stage = "asr"
    audio_id = body.audio_id.strip()
    if not audio_id:
        raise AppError(
            status_code=422,
            code="MISSING_FIELD",
            message="请提供有效的 audio_id。",
            stage=stage,
            request_id=request_id,
        )

    meta, raw = read_audio_bytes(audio_id, request_id=request_id, stage=stage)
    text = await transcribe_audio(
        raw=raw,
        content_type=meta.content_type,
        request_id=request_id,
    )
    logger.info(
        "asr_endpoint_ok request_id=%s audio_id=%s text_chars=%s",
        request_id,
        audio_id,
        len(text),
    )
    return AsrResponse(request_id=request_id, data=AsrData(text=text))
