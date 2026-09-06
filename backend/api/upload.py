import logging

from fastapi import APIRouter, File, UploadFile

from api import new_request_id
from config import get_settings
from schemas import AppError, UploadData, UploadResponse
from services.audio_probe import probe_audio_bytes
from services.audio_store import save_audio

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])


@router.post(
    "/upload",
    response_model=UploadResponse,
    responses={
        413: {"description": "File too large"},
        415: {"description": "Unsupported media type"},
        422: {"description": "Invalid duration or request"},
    },
)
async def upload_audio(file: UploadFile = File(..., description="录音文件，字段名 file")) -> UploadResponse:
    request_id = new_request_id()
    settings = get_settings()
    stage = "upload"

    if file is None:
        raise AppError(
            status_code=422,
            code="MISSING_FIELD",
            message="请使用字段名 file 上传录音文件。",
            stage=stage,
            request_id=request_id,
        )

    # Read at most max+1 bytes to enforce size without trusting client headers alone.
    data = await file.read(settings.max_audio_bytes + 1)
    if not data:
        raise AppError(
            status_code=422,
            code="MISSING_FIELD",
            message="上传的录音文件为空，请重新录制后上传。",
            stage=stage,
            request_id=request_id,
        )
    if len(data) > settings.max_audio_bytes:
        raise AppError(
            status_code=413,
            code="FILE_TOO_LARGE",
            message="录音文件不能超过 5MB，请缩短录音后重试。",
            stage=stage,
            request_id=request_id,
        )

    try:
        probe = probe_audio_bytes(data, request_id=request_id)
    except AppError:
        raise

    if probe.duration_sec < settings.min_audio_duration_sec:
        raise AppError(
            status_code=422,
            code="INVALID_DURATION",
            message="录音时长需在 1 到 60 秒之间，请重新录制。",
            stage=stage,
            request_id=request_id,
        )
    if probe.duration_sec > settings.max_audio_duration_sec:
        raise AppError(
            status_code=422,
            code="INVALID_DURATION",
            message="录音时长需在 1 到 60 秒之间，请重新录制。",
            stage=stage,
            request_id=request_id,
        )

    meta = save_audio(
        data=data,
        probe_format_name=probe.format_name,
        probe_codec_name=probe.codec_name,
        duration_sec=probe.duration_sec,
        content_type=probe.content_type,
        extension=probe.extension,
        original_filename=file.filename,
    )
    logger.info(
        "upload_ok request_id=%s audio_id=%s duration_source=%s duration_sec=%.3f",
        request_id,
        meta.audio_id,
        probe.duration_source,
        probe.duration_sec,
    )
    return UploadResponse(
        request_id=request_id,
        data=UploadData(audio_id=meta.audio_id),
    )
