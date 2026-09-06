from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from schemas import AppError, ProbeResult

client = TestClient(app)


def _probe(
    *,
    duration_sec: float = 3.5,
    format_name: str = "matroska,webm",
    codec_name: str = "opus",
) -> ProbeResult:
    return ProbeResult(
        format_name=format_name,
        codec_name=codec_name,
        duration_sec=duration_sec,
        duration_source="packets",
        content_type="audio/webm",
        extension="webm",
    )


def _settings(tmp_path: Path) -> MagicMock:
    settings = MagicMock()
    settings.max_audio_bytes = 5 * 1024 * 1024
    settings.min_audio_duration_sec = 1.0
    settings.max_audio_duration_sec = 60.0
    settings.audio_storage_dir = tmp_path
    settings.audio_ttl_hours = 24
    return settings


def test_upload_success(tmp_path: Path):
    fake_bytes = b"fake-webm-bytes-for-upload-test"
    settings = _settings(tmp_path)
    with (
        patch("api.upload.probe_audio_bytes", return_value=_probe()),
        patch("api.upload.get_settings", return_value=settings),
        patch("services.audio_store.get_settings", return_value=settings),
    ):
        response = client.post(
            "/upload",
            files={"file": ("clip.webm", fake_bytes, "audio/webm")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    assert body["data"]["audio_id"].startswith("aud_")
    audio_id = body["data"]["audio_id"]
    assert (tmp_path / f"{audio_id}.webm").exists()
    assert (tmp_path / f"{audio_id}.meta.json").exists()
    meta_text = (tmp_path / f"{audio_id}.meta.json").read_text(encoding="utf-8")
    assert "created_at" in meta_text
    assert str(tmp_path) not in body["data"]["audio_id"]


def test_upload_file_too_large():
    oversized = b"x" * (5 * 1024 * 1024 + 1)
    response = client.post(
        "/upload",
        files={"file": ("big.webm", oversized, "audio/webm")},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "FILE_TOO_LARGE"
    assert body["error"]["stage"] == "upload"
    assert body["request_id"]
    assert "error" in body
    assert "message" in body["error"]


def test_upload_unsupported_format():
    with patch(
        "api.upload.probe_audio_bytes",
        side_effect=AppError(
            status_code=415,
            code="UNSUPPORTED_MEDIA_TYPE",
            message="不支持的音频格式，请使用浏览器录制的 WebM/Opus 文件。",
            stage="upload",
            request_id="req_test",
        ),
    ):
        response = client.post(
            "/upload",
            files={"file": ("clip.mp3", b"id3-fake", "audio/mpeg")},
        )
    assert response.status_code == 415
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert body["error"]["stage"] == "upload"
    assert body["request_id"]


@pytest.mark.parametrize("duration", [0.5, 61.0])
def test_upload_invalid_duration(duration: float, tmp_path: Path):
    settings = _settings(tmp_path)
    with (
        patch("api.upload.probe_audio_bytes", return_value=_probe(duration_sec=duration)),
        patch("api.upload.get_settings", return_value=settings),
        patch("services.audio_store.get_settings", return_value=settings),
    ):
        response = client.post(
            "/upload",
            files={"file": ("clip.webm", b"fake-bytes", "audio/webm")},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_DURATION"
    assert body["error"]["stage"] == "upload"
    assert body["request_id"]


def test_upload_missing_file_field():
    response = client.post("/upload", data={})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "MISSING_FIELD"
    assert body["error"]["stage"] == "upload"
    assert body["request_id"]
