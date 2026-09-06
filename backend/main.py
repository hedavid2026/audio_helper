import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import new_request_id
from api.asr import router as asr_router
from api.extract import router as extract_router
from api.health import router as health_router
from api.upload import router as upload_router
from config import get_settings
from schemas import AppError, ErrorDetail, ErrorResponse
from services.audio_store import cleanup_expired_audio, ensure_audio_storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title="Voice Meetup Helper", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(upload_router)
app.include_router(asr_router)
app.include_router(extract_router)


@app.on_event("startup")
def on_startup() -> None:
    ensure_audio_storage()
    removed = cleanup_expired_audio()
    logger.info("startup_audio_cleanup removed=%s", removed)


def _stage_from_path(path: str) -> str:
    normalized = path.rstrip("/")
    if normalized.endswith("/asr"):
        return "asr"
    if normalized.endswith("/upload"):
        return "upload"
    if normalized.endswith("/extract"):
        return "extract"
    return "request"


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    request_id = exc.request_id or new_request_id()
    body = ErrorResponse(
        request_id=request_id,
        error=ErrorDetail(code=exc.code, message=exc.message, stage=exc.stage),
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = new_request_id()
    stage = _stage_from_path(request.url.path)
    logger.info("validation_error request_id=%s stage=%s detail=%s", request_id, stage, exc.errors())
    if stage == "asr":
        message = "请求参数不正确，请提供 JSON 字段 audio_id。"
    elif stage == "upload":
        message = "请求参数不正确，请检查是否使用字段名 file 上传文件。"
    elif stage == "extract":
        message = "请求参数不正确，请提供 JSON 字段 text，以及可选的 city。"
    else:
        message = "请求参数不正确，请检查后重试。"
    body = ErrorResponse(
        request_id=request_id,
        error=ErrorDetail(
            code="MISSING_FIELD",
            message=message,
            stage=stage,
        ),
    )
    return JSONResponse(status_code=422, content=body.model_dump())
