from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from main import app
from schemas import AppError, AudioMeta
from services import bailian_asr

client = TestClient(app)


def _meta(audio_id: str = "aud_test123") -> AudioMeta:
    return AudioMeta(
        audio_id=audio_id,
        created_at=datetime.now(timezone.utc),
        size_bytes=128,
        duration_sec=3.2,
        format_name="matroska,webm",
        codec_name="opus",
        content_type="audio/webm",
        extension="webm",
        original_filename="clip.webm",
    )


def test_asr_success():
    with (
        patch(
            "api.asr.read_audio_bytes",
            return_value=(_meta(), b"fake-audio"),
        ),
        patch(
            "api.asr.transcribe_audio",
            new=AsyncMock(return_value="我在杭州东站，朋友在西湖龙翔桥地铁站。"),
        ),
    ):
        response = client.post("/asr", json={"audio_id": "aud_test123"})

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    assert body["data"]["text"] == "我在杭州东站，朋友在西湖龙翔桥地铁站。"


def test_asr_audio_not_found():
    with patch(
        "api.asr.read_audio_bytes",
        side_effect=AppError(
            status_code=404,
            code="AUDIO_NOT_FOUND",
            message="录音不存在或已过期，请重新上传。",
            stage="asr",
            request_id="req_x",
        ),
    ):
        response = client.post("/asr", json={"audio_id": "aud_missing"})

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "AUDIO_NOT_FOUND"
    assert body["error"]["stage"] == "asr"


def test_asr_empty_transcript():
    with (
        patch(
            "api.asr.read_audio_bytes",
            return_value=(_meta(), b"fake-audio"),
        ),
        patch(
            "api.asr.transcribe_audio",
            new=AsyncMock(
                side_effect=AppError(
                    status_code=422,
                    code="EMPTY_TRANSCRIPT",
                    message="没有识别到有效文字，请重新说明两位的位置和碰面需求。",
                    stage="asr",
                    request_id="req_e",
                )
            ),
        ),
    ):
        response = client.post("/asr", json={"audio_id": "aud_test123"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "EMPTY_TRANSCRIPT"
    assert body["error"]["stage"] == "asr"


def test_asr_timeout():
    with (
        patch(
            "api.asr.read_audio_bytes",
            return_value=(_meta(), b"fake-audio"),
        ),
        patch(
            "api.asr.transcribe_audio",
            new=AsyncMock(
                side_effect=AppError(
                    status_code=504,
                    code="ASR_TIMEOUT",
                    message="语音识别超时，请稍后重试。",
                    stage="asr",
                    request_id="req_t",
                )
            ),
        ),
    ):
        response = client.post("/asr", json={"audio_id": "aud_test123"})

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "ASR_TIMEOUT"


def test_asr_missing_field():
    response = client.post("/asr", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "MISSING_FIELD"
    assert body["error"]["stage"] == "asr"


def test_asr_expired_meta(tmp_path: Path):
    audio_id = "aud_expired001"
    stale = datetime.now(timezone.utc) - timedelta(hours=25)
    meta = AudioMeta(
        audio_id=audio_id,
        created_at=stale,
        size_bytes=10,
        duration_sec=2.0,
        format_name="webm",
        codec_name="opus",
        content_type="audio/webm",
        extension="webm",
        original_filename="old.webm",
    )
    (tmp_path / f"{audio_id}.webm").write_bytes(b"12345")
    (tmp_path / f"{audio_id}.meta.json").write_text(meta.model_dump_json(), encoding="utf-8")

    with patch("services.audio_store.get_settings") as settings_mock:
        settings = settings_mock.return_value
        settings.audio_storage_dir = tmp_path
        settings.audio_ttl_hours = 24
        response = client.post("/asr", json={"audio_id": audio_id})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AUDIO_NOT_FOUND"


@pytest.mark.asyncio
async def test_transcribe_rejects_large_base64(monkeypatch):
    class _Settings:
        bailian_api_key = "sk-test"
        bailian_asr_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        bailian_asr_model = "qwen3-asr-flash"
        asr_max_base64_bytes = 10
        asr_timeout_sec = 1.0
        asr_enable_itn = False

    monkeypatch.setattr(bailian_asr, "get_settings", lambda: _Settings())
    with pytest.raises(AppError) as exc_info:
        await bailian_asr.transcribe_audio(
            raw=b"0123456789abcdef",
            content_type="audio/webm",
            request_id="req_b64",
        )
    assert exc_info.value.code == "ASR_PAYLOAD_TOO_LARGE"
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_transcribe_maps_timeout(monkeypatch):
    class _Settings:
        bailian_api_key = "sk-test"
        bailian_asr_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        bailian_asr_model = "qwen3-asr-flash"
        asr_max_base64_bytes = 10 * 1024 * 1024
        asr_timeout_sec = 0.01
        asr_enable_itn = False

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(bailian_asr, "get_settings", lambda: _Settings())
    monkeypatch.setattr(bailian_asr.httpx, "AsyncClient", _FakeClient)
    with pytest.raises(AppError) as exc_info:
        await bailian_asr.transcribe_audio(
            raw=b"abc",
            content_type="audio/webm",
            request_id="req_to",
        )
    assert exc_info.value.code == "ASR_TIMEOUT"
    assert exc_info.value.status_code == 504
