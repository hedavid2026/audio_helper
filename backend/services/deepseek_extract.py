import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError, field_validator

from config import get_settings
from schemas import AppError, ExtractData

logger = logging.getLogger(__name__)

STAGE = "extract"
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract_meetup.txt"

_VAGUE_ADDRESS_EXACT = {
    "家",
    "我家",
    "家里",
    "公司",
    "单位",
    "学校",
    "附近",
    "这边",
    "那边",
}


class ExtractModelOutput(BaseModel):
    """Raw model JSON. Nulls allowed; validated before business checks."""

    city_a: str | None = None
    address_a: str | None = None
    city_b: str | None = None
    address_b: str | None = None
    category: str | None = None
    party_count: int | None = None
    incomplete_reason: str | None = None

    @field_validator(
        "city_a",
        "address_a",
        "city_b",
        "address_b",
        "category",
        "incomplete_reason",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("party_count", mode="before")
    @classmethod
    def coerce_party_count(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("party_count must be an integer")
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value


def load_extract_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", stripped, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return stripped


def parse_model_output(content: str, *, request_id: str) -> ExtractModelOutput:
    cleaned = _strip_code_fence(content)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.info("extract_invalid_json request_id=%s", request_id)
        raise AppError(
            status_code=502,
            code="MODEL_OUTPUT_INVALID",
            message="地址解析服务返回异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        ) from exc

    if not isinstance(payload, dict):
        raise AppError(
            status_code=502,
            code="MODEL_OUTPUT_INVALID",
            message="地址解析服务返回异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        )

    required = {
        "city_a",
        "address_a",
        "city_b",
        "address_b",
        "category",
        "party_count",
        "incomplete_reason",
    }
    missing = required - set(payload.keys())
    if missing:
        logger.info(
            "extract_missing_fields request_id=%s missing=%s",
            request_id,
            sorted(missing),
        )
        raise AppError(
            status_code=502,
            code="MODEL_OUTPUT_INVALID",
            message="地址解析服务返回异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        )

    try:
        return ExtractModelOutput.model_validate(payload)
    except ValidationError as exc:
        logger.info("extract_schema_invalid request_id=%s", request_id)
        raise AppError(
            status_code=502,
            code="MODEL_OUTPUT_INVALID",
            message="地址解析服务返回异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        ) from exc


def normalize_city(city: str | None) -> str | None:
    if city is None:
        return None
    text = city.strip()
    if text.endswith("市") and len(text) > 1:
        text = text[:-1]
    return text or None


def cities_equal(a: str | None, b: str | None) -> bool:
    na = normalize_city(a)
    nb = normalize_city(b)
    if na is None or nb is None:
        return False
    return na == nb


def is_vague_address(address: str | None) -> bool:
    if address is None:
        return True
    text = address.strip()
    if not text:
        return True
    if text in _VAGUE_ADDRESS_EXACT:
        return True
    vague_prefixes = ("我家", "家里", "公司", "单位")
    if any(text == p or text.startswith(p + "附近") for p in vague_prefixes):
        if len(text) <= 6:
            return True
    return False


def apply_page_city_defaults(
    model: ExtractModelOutput, page_city: str
) -> ExtractModelOutput:
    page = page_city.strip() or "杭州"
    data = model.model_dump()
    if data["city_a"] is None and not is_vague_address(data["address_a"]):
        data["city_a"] = page
    if data["city_b"] is None and not is_vague_address(data["address_b"]):
        data["city_b"] = page
    if data["category"] is None:
        data["category"] = "咖啡店"
    return ExtractModelOutput.model_validate(data)


def to_public_extract_data(model: ExtractModelOutput) -> ExtractData:
    assert model.city_a and model.address_a and model.city_b and model.address_b
    assert model.category
    return ExtractData(
        city_a=model.city_a,
        address_a=model.address_a,
        city_b=model.city_b,
        address_b=model.address_b,
        category=model.category,
    )


def validate_business_completeness(
    model: ExtractModelOutput, *, request_id: str
) -> ExtractData:
    if model.party_count is None:
        raise AppError(
            status_code=422,
            code="PARTY_COUNT_INVALID",
            message="无法确认碰面人数，请重新说明是两个人在哪里碰面。",
            stage=STAGE,
            request_id=request_id,
        )
    if model.party_count != 2:
        raise AppError(
            status_code=422,
            code="PARTY_COUNT_INVALID",
            message="当前仅支持两个人碰面，请重新说明两位的位置。",
            stage=STAGE,
            request_id=request_id,
        )

    if is_vague_address(model.address_a) or is_vague_address(model.address_b):
        raise AppError(
            status_code=422,
            code="MISSING_ADDRESS",
            message="地址不够明确，请说出具体地点（例如车站、地铁站或地标），不要只说家里或公司。",
            stage=STAGE,
            request_id=request_id,
        )

    if model.city_a is None or model.city_b is None:
        raise AppError(
            status_code=422,
            code="MISSING_ADDRESS",
            message="缺少城市信息，请说明两位所在城市，或在页面选择默认城市后重试。",
            stage=STAGE,
            request_id=request_id,
        )

    if not cities_equal(model.city_a, model.city_b):
        raise AppError(
            status_code=422,
            code="CROSS_CITY",
            message="当前仅支持同一城市内两人碰面，请重新说明两位都在同一城市的位置。",
            stage=STAGE,
            request_id=request_id,
        )

    if not model.category:
        model = model.model_copy(update={"category": "咖啡店"})

    return to_public_extract_data(model)


async def extract_meetup_info(
    *,
    text: str,
    page_city: str,
    request_id: str,
) -> ExtractData:
    settings = get_settings()
    if not settings.deepseek_api_key.strip():
        raise AppError(
            status_code=502,
            code="EXTRACT_NOT_CONFIGURED",
            message="未配置 DeepSeek API Key，请在 backend/.env 填写 DEEPSEEK_API_KEY 后重试。",
            stage=STAGE,
            request_id=request_id,
        )

    system_prompt = load_extract_prompt()
    user_payload = {
        "user_text": text,
        "page_city": page_city.strip() or "杭州",
    }
    base_url = settings.deepseek_base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "stream": False,
    }

    logger.info(
        "extract_request request_id=%s model=%s text_chars=%s page_city=%s",
        request_id,
        settings.deepseek_model,
        len(text),
        page_city,
    )

    try:
        async with httpx.AsyncClient(timeout=settings.extract_timeout_sec) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        logger.info("extract_timeout request_id=%s", request_id)
        raise AppError(
            status_code=504,
            code="EXTRACT_TIMEOUT",
            message="地址解析超时，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        ) from exc
    except httpx.HTTPError as exc:
        logger.info(
            "extract_http_error request_id=%s error_type=%s",
            request_id,
            type(exc).__name__,
        )
        raise AppError(
            status_code=502,
            code="EXTRACT_UPSTREAM_ERROR",
            message="地址解析服务异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        ) from exc

    if response.status_code >= 400:
        logger.info(
            "extract_upstream_status request_id=%s status_code=%s",
            request_id,
            response.status_code,
        )
        raise AppError(
            status_code=502,
            code="EXTRACT_UPSTREAM_ERROR",
            message="地址解析服务返回异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise AppError(
            status_code=502,
            code="MODEL_OUTPUT_INVALID",
            message="地址解析服务返回异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        ) from exc

    content = None
    try:
        content = payload["choices"][0]["message"]["content"]
    except (TypeError, KeyError, IndexError):
        content = None
    if not isinstance(content, str) or not content.strip():
        raise AppError(
            status_code=502,
            code="MODEL_OUTPUT_INVALID",
            message="地址解析服务返回异常，请稍后重试。",
            stage=STAGE,
            request_id=request_id,
        )

    model_out = parse_model_output(content, request_id=request_id)
    model_out = apply_page_city_defaults(model_out, page_city)
    result = validate_business_completeness(model_out, request_id=request_id)
    logger.info(
        "extract_ok request_id=%s category=%s",
        request_id,
        result.category,
    )
    return result
