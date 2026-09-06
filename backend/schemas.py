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
