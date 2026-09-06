from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bailian_api_key: str = ""
    bailian_asr_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_asr_model: str = "qwen3-asr-flash"
    bailian_tts_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    bailian_tts_model: str = "qwen3-tts-flash"
    bailian_tts_voice: str = "Cherry"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    amap_api_key: str = ""

    cors_origins: str = "http://localhost:5175"
    host: str = "0.0.0.0"
    port: int = 8003

    storage_dir: str = str(_BACKEND_DIR / "storage")
    audio_ttl_hours: int = 24
    max_audio_bytes: int = 5 * 1024 * 1024
    min_audio_duration_sec: float = 1.0
    max_audio_duration_sec: float = 60.0
    ffprobe_path: str = "ffprobe"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def audio_storage_dir(self) -> Path:
        return Path(self.storage_dir) / "audio"


@lru_cache
def get_settings() -> Settings:
    return Settings()
