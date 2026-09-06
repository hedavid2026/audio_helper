import json
import logging
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from config import get_settings
from schemas import AppError, AudioMeta, ensure_aware, utc_now

logger = logging.getLogger(__name__)


def new_audio_id() -> str:
    return f"aud_{uuid4().hex}"


def _meta_path(audio_id: str) -> Path:
    return get_settings().audio_storage_dir / f"{audio_id}.meta.json"


def _data_path(audio_id: str, extension: str) -> Path:
    return get_settings().audio_storage_dir / f"{audio_id}.{extension}"


def ensure_audio_storage() -> Path:
    path = get_settings().audio_storage_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_audio(
    *,
    data: bytes,
    probe_format_name: str,
    probe_codec_name: str,
    duration_sec: float,
    content_type: str,
    extension: str,
    original_filename: str | None,
) -> AudioMeta:
    ensure_audio_storage()
    audio_id = new_audio_id()
    meta = AudioMeta(
        audio_id=audio_id,
        created_at=utc_now(),
        size_bytes=len(data),
        duration_sec=duration_sec,
        format_name=probe_format_name,
        codec_name=probe_codec_name,
        content_type=content_type,
        extension=extension,
        original_filename=original_filename,
    )

    data_file = _data_path(audio_id, extension)
    meta_file = _meta_path(audio_id)
    data_file.write_bytes(data)
    meta_file.write_text(meta.model_dump_json(), encoding="utf-8")
    logger.info(
        "audio_saved audio_id=%s size_bytes=%s duration_sec=%.3f",
        audio_id,
        meta.size_bytes,
        meta.duration_sec,
    )
    return meta


def load_audio_meta(
    audio_id: str,
    *,
    request_id: str | None = None,
    stage: str = "upload",
) -> AudioMeta:
    """Load metadata and enforce TTL. Ready for later readers such as /asr."""
    meta_file = _meta_path(audio_id)
    if not meta_file.exists():
        raise AppError(
            status_code=404,
            code="AUDIO_NOT_FOUND",
            message="录音不存在或已过期，请重新上传。",
            stage=stage,
            request_id=request_id,
        )

    meta = AudioMeta.model_validate_json(meta_file.read_text(encoding="utf-8"))
    age = utc_now() - ensure_aware(meta.created_at)
    if age > timedelta(hours=get_settings().audio_ttl_hours):
        raise AppError(
            status_code=404,
            code="AUDIO_NOT_FOUND",
            message="录音不存在或已过期，请重新上传。",
            stage=stage,
            request_id=request_id,
        )

    data_file = _data_path(audio_id, meta.extension)
    if not data_file.exists():
        raise AppError(
            status_code=404,
            code="AUDIO_NOT_FOUND",
            message="录音不存在或已过期，请重新上传。",
            stage=stage,
            request_id=request_id,
        )
    return meta


def resolve_audio_file(
    audio_id: str,
    *,
    request_id: str | None = None,
    stage: str = "upload",
) -> tuple[AudioMeta, Path]:
    meta = load_audio_meta(audio_id, request_id=request_id, stage=stage)
    return meta, _data_path(audio_id, meta.extension)


def cleanup_expired_audio() -> int:
    """Remove expired temp audio. Does not replace read-time expiry checks."""
    settings = get_settings()
    root = ensure_audio_storage()
    removed = 0
    now = utc_now()
    for meta_file in root.glob("*.meta.json"):
        try:
            meta = AudioMeta.model_validate_json(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            logger.warning("skip_invalid_audio_meta path=%s", meta_file.name)
            continue

        age = now - ensure_aware(meta.created_at)
        if age <= timedelta(hours=settings.audio_ttl_hours):
            continue

        data_file = _data_path(meta.audio_id, meta.extension)
        try:
            if data_file.exists():
                data_file.unlink()
            meta_file.unlink(missing_ok=True)
            removed += 1
            logger.info("expired_audio_removed audio_id=%s", meta.audio_id)
        except OSError:
            logger.exception("failed_removing_expired_audio audio_id=%s", meta.audio_id)
    return removed
