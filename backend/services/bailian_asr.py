import base64
import logging
from typing import Any

import httpx

from config import get_settings
from schemas import AppError

logger = logging.getLogger(__name__)

STAGE = "asr"


def _extract_transcript(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "".join(parts).strip() or None
    return None


def build_data_uri(*, content_type: str, raw: bytes) -> tuple[str, str]:
    mime = content_type or "audio/webm"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}", encoded


async def transcribe_audio(
    *,
    raw: bytes,
    content_type: str,
    request_id: str,
) -> str:
    settings = get_settings()
    if not settings.bailian_api_key.strip():
        raise AppError(
            status_code=502,
            code="ASR_NOT_CONFIGURED",
            message="未配置百炼 API Key，请在 backend/.env 填写 BAILIAN_API_KEY 后重试。",
            stage=STAGE,
            request_id=request_id,
        )

    data_uri, encoded = build_data_uri(content_type=content_type, raw=raw)
    encoded_size = len(encoded.encode("ascii"))
    if encoded_size > settings.asr_max_base64_bytes:
        raise AppError(
            status_code=413,
            code="ASR_PAYLOAD_TOO_LARGE",
            message="音频 Base64 编码后超过供应商限制，请缩短录音后重试。",
            stage=STAGE,
            request_id=request_id,
        )

    base_url = settings.bailian_asr_base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.bailian_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.bailian_asr_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_uri},
                    }
                ],
            }
        ],
        "stream": False,
        "asr_options": {
            "enable_itn": settings.asr_enable_itn,
        },
    }

    logger.info(
        "asr_request request_id=%s model=%s raw_bytes=%s base64_bytes=%s",
        request_id,
        settings.bailian_asr_model,
        len(raw),
        encoded_size,
    )

    try:
        async with httpx.AsyncClient(timeout=settings.asr_timeout_sec) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        logger.info("asr_timeout request_id=%s", request_id)
        raise AppError(
            status_code=504,
            code="ASR_TIMEOUT",
            message="语音识别超时，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        ) from exc
    except httpx.HTTPError as exc:
        logger.info("asr_http_error request_id=%s error_type=%s", request_id, type(exc).__name__)
        raise AppError(
            status_code=502,
            code="ASR_UPSTREAM_ERROR",
            message="语音识别服务异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        ) from exc

    if response.status_code >= 400:
        logger.info(
            "asr_upstream_status request_id=%s status_code=%s",
            request_id,
            response.status_code,
        )
        raise AppError(
            status_code=502,
            code="ASR_UPSTREAM_ERROR",
            message="语音识别服务返回异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        logger.info("asr_invalid_json request_id=%s", request_id)
        raise AppError(
            status_code=502,
            code="ASR_UPSTREAM_ERROR",
            message="语音识别服务返回无法解析，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        ) from exc

    text = _extract_transcript(payload if isinstance(payload, dict) else {})
    if not text:
        raise AppError(
            status_code=422,
            code="EMPTY_TRANSCRIPT",
            message="没有识别到有效文字，请重新说明两位的位置和碰面需求。",
            stage=STAGE,
            request_id=request_id,
        )

    logger.info(
        "asr_ok request_id=%s text_chars=%s",
        request_id,
        len(text),
    )
    return text
