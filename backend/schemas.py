from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    request_id: str
    data: T


class ErrorDetail(BaseModel):
    code: str
    message: str
    stage: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorDetail


class HealthData(BaseModel):
    status: str = Field(examples=["ok"])


class HealthResponse(SuccessResponse[HealthData]):
    pass


class UploadData(BaseModel):
    audio_id: str = Field(examples=["aud_0123456789abcdef"])


class UploadResponse(SuccessResponse[UploadData]):
    pass


class AsrRequest(BaseModel):
    audio_id: str = Field(examples=["aud_0123456789abcdef"])


class AsrData(BaseModel):
    text: str


class AsrResponse(SuccessResponse[AsrData]):
    pass


class ExtractRequest(BaseModel):
    text: str = Field(examples=["我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。"])
    city: str = Field(default="杭州", examples=["杭州"])


class ExtractData(BaseModel):
    city_a: str
    address_a: str
    city_b: str
    address_b: str
    category: str


class ExtractResponse(SuccessResponse[ExtractData]):
    pass


class AudioMeta(BaseModel):
    audio_id: str
    created_at: datetime
    size_bytes: int
    duration_sec: float
    format_name: str
    codec_name: str
    content_type: str
    extension: str
    original_filename: str | None = None


class ProbeResult(BaseModel):
    format_name: str
    codec_name: str
    duration_sec: float
    duration_source: str = Field(description="format | stream | packets")
    content_type: str
    extension: str


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        stage: str,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.stage = stage
        self.request_id = request_id
        super().__init__(message)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
