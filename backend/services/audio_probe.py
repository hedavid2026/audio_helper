import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from config import get_settings
from schemas import AppError, ProbeResult

logger = logging.getLogger(__name__)

ALLOWED_FORMAT_TOKENS = {"webm", "matroska"}
ALLOWED_CODECS = {"opus"}


def _raise_probe_missing(request_id: str | None) -> None:
    raise AppError(
        status_code=500,
        code="PROBE_DEPENDENCY_MISSING",
        message="服务器缺少音频探测工具 ffprobe，请安装 FFmpeg 后重试。",
        stage="upload",
        request_id=request_id,
    )


def _run_ffprobe(args: list[str], *, request_id: str | None) -> dict:
    settings = get_settings()
    ffprobe = settings.ffprobe_path
    if shutil.which(ffprobe) is None and not Path(ffprobe).exists():
        _raise_probe_missing(request_id)

    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        *args,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        _raise_probe_missing(request_id)
    except subprocess.TimeoutExpired as exc:
        raise AppError(
            status_code=504,
            code="PROBE_TIMEOUT",
            message="音频探测超时，请换一段较短录音后重试。",
            stage="upload",
            request_id=request_id,
        ) from exc

    if completed.returncode != 0:
        logger.info(
            "ffprobe_failed returncode=%s stderr=%s",
            completed.returncode,
            (completed.stderr or "")[:300],
        )
        raise AppError(
            status_code=415,
            code="UNSUPPORTED_MEDIA_TYPE",
            message="不支持的音频格式，请使用浏览器录制的 WebM/Opus 文件。",
            stage="upload",
            request_id=request_id,
        )

    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AppError(
            status_code=502,
            code="PROBE_OUTPUT_INVALID",
            message="音频探测结果异常，请稍后重试。",
            stage="upload",
            request_id=request_id,
        ) from exc


def _parse_duration(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text or text.upper() == "N/A":
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if number <= 0:
        return None
    return number


def _duration_from_packets(path: Path, *, request_id: str | None) -> float | None:
    """Estimate duration from packet timestamps when container Duration is missing."""
    settings = get_settings()
    ffprobe = settings.ffprobe_path
    if shutil.which(ffprobe) is None and not Path(ffprobe).exists():
        _raise_probe_missing(request_id)

    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "packet=pts_time",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        _raise_probe_missing(request_id)
    except subprocess.TimeoutExpired as exc:
        raise AppError(
            status_code=504,
            code="PROBE_TIMEOUT",
            message="音频探测超时，请换一段较短录音后重试。",
            stage="upload",
            request_id=request_id,
        ) from exc

    if completed.returncode != 0:
        logger.info(
            "ffprobe_packets_failed returncode=%s stderr=%s",
            completed.returncode,
            (completed.stderr or "")[:300],
        )
        return None

    last_pts = None
    for line in (completed.stdout or "").splitlines():
        pts = _parse_duration(line.strip())
        if pts is None:
            continue
        if last_pts is None or pts > last_pts:
            last_pts = pts
    return last_pts

def _pick_extension(format_name: str) -> str:
    tokens = {part.strip().lower() for part in format_name.split(",") if part.strip()}
    if "webm" in tokens:
        return "webm"
    if "matroska" in tokens:
        return "webm"
    return "webm"


def _pick_content_type(format_name: str) -> str:
    tokens = {part.strip().lower() for part in format_name.split(",") if part.strip()}
    if "webm" in tokens or "matroska" in tokens:
        return "audio/webm"
    return "application/octet-stream"


def probe_audio_bytes(data: bytes, *, request_id: str | None = None) -> ProbeResult:
    """Probe real container/codec/duration via ffprobe (probe only, no transcoding)."""
    with tempfile.NamedTemporaryFile(suffix=".upload", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        payload = _run_ffprobe(
            [
                "-show_entries",
                "format=format_name,duration:stream=index,codec_type,codec_name,duration",
                "-show_streams",
                str(tmp_path),
            ],
            request_id=request_id,
        )

        format_info = payload.get("format") or {}
        format_name = str(format_info.get("format_name") or "").strip().lower()
        if not format_name:
            raise AppError(
                status_code=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="无法识别音频容器格式，请重新录制后上传。",
                stage="upload",
                request_id=request_id,
            )

        format_tokens = {
            part.strip().lower() for part in format_name.split(",") if part.strip()
        }
        if not format_tokens.intersection(ALLOWED_FORMAT_TOKENS):
            raise AppError(
                status_code=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="不支持的音频格式，请使用浏览器录制的 WebM/Opus 文件。",
                stage="upload",
                request_id=request_id,
            )

        streams = payload.get("streams") or []
        audio_streams = [
            stream
            for stream in streams
            if str(stream.get("codec_type", "")).lower() == "audio"
        ]
        if not audio_streams:
            raise AppError(
                status_code=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="文件中未找到音频编码轨道，请重新录制后上传。",
                stage="upload",
                request_id=request_id,
            )

        codec_name = str(audio_streams[0].get("codec_name") or "").strip().lower()
        if codec_name not in ALLOWED_CODECS:
            raise AppError(
                status_code=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="仅支持 Opus 编码的 WebM 录音，请更换浏览器或重新录制。",
                stage="upload",
                request_id=request_id,
            )

        duration = _parse_duration(format_info.get("duration"))
        duration_source = "format"
        if duration is None:
            duration = _parse_duration(audio_streams[0].get("duration"))
            duration_source = "stream"
        if duration is None:
            duration = _duration_from_packets(tmp_path, request_id=request_id)
            duration_source = "packets"

        if duration is None:
            raise AppError(
                status_code=422,
                code="INVALID_DURATION",
                message="无法测定录音时长，请重新录制后再上传。",
                stage="upload",
                request_id=request_id,
            )

        return ProbeResult(
            format_name=format_name,
            codec_name=codec_name,
            duration_sec=duration,
            duration_source=duration_source,
            content_type=_pick_content_type(format_name),
            extension=_pick_extension(format_name),
        )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("temp_probe_file_cleanup_failed path=%s", tmp_path)
