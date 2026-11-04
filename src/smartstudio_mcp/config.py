from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CARTA_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    environment: Literal["development", "production", "demo"] = "development"
    public_origin: str = ""
    canonical_origin: str = ""
    local_test_only: bool = False
    ephemeris_dir: Path = Path("data/ephemeris")
    data_manifest: Path = Path("data/ephemeris-manifest.json")
    allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    allowed_origins: list[str] = ["http://localhost:*", "http://127.0.0.1:*"]
    max_body_bytes: int = Field(default=32768, ge=1024, le=1048576)
    rate_per_minute: int = Field(default=60, ge=1, le=10000)
    global_rate_per_minute: int = Field(default=600, ge=1, le=100000)
    max_concurrent: int = Field(default=8, ge=1, le=64)
    request_timeout: float = Field(default=15.0, ge=1, le=60)
    geocoder: Literal["disabled", "nominatim"] = "disabled"
    geocoder_url: str = ""
    geocoder_user_agent: str = (
        "SmartStudio-CartaYArcano/0.1 (https://smartstudio.dev/carta-y-arcano)"
    )
    geocoder_min_interval: float = Field(default=1.1, ge=1.0)
    source_url: str = ""
    source_archive: Path = Path("artifacts/source.tar.gz")
    license_review_approved: bool = False
    release_revision: str = "development"
    openai_challenge_token: str = ""
    metrics_token: str = ""

    @model_validator(mode="after")
    def deployment_policy(self):
        if self.environment == "demo" and self.geocoder != "disabled":
            raise ValueError("Demo must disable external geocoding")
        if self.local_test_only:
            origin = urlparse(self.public_origin)
            if origin.scheme != "http" or origin.hostname != "127.0.0.1":
                raise ValueError("Local tests require an explicit HTTP loopback origin")
        return self
