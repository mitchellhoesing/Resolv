"""Configuration loading via pydantic-settings.

Sources are merged with this precedence (later wins on conflict):
    TOML file (config/settings.toml) -> .env file -> process environment -> init kwargs.

Secrets are env-only; they never appear in the TOML file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TOML = _PROJECT_ROOT / "config" / "settings.toml"


class CoderSettings(BaseModel):
    backend: Literal["claude_code", "litellm"] = "claude_code"
    claude_model: str = "claude-opus-4-7"
    litellm_model: str = "gpt-4o"


class LoopSettings(BaseModel):
    max_iterations: int = Field(default=5, ge=1, le=20)


class ContextSettings(BaseModel):
    max_chunks: int = Field(default=20, ge=1, le=200)


class DeliverySettings(BaseModel):
    base_branch: str = "main"
    branch_prefix: str = "resolv/issue-"


class SandboxSettings(BaseModel):
    image_tag: str = "resolv-sandbox:latest"
    qa_timeout_seconds: int = Field(default=300, ge=30)
    test_timeout_seconds: int = Field(default=600, ge=30)


class WebhookSettings(BaseModel):
    trigger_phrase: str = "/resolv fix"
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)


class Settings(BaseSettings):
    coder: CoderSettings = CoderSettings()
    loop: LoopSettings = LoopSettings()
    context: ContextSettings = ContextSettings()
    delivery: DeliverySettings = DeliverySettings()
    sandbox: SandboxSettings = SandboxSettings()
    webhook: WebhookSettings = WebhookSettings()

    github_token: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    github_webhook_secret: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        toml_file=str(_DEFAULT_TOML),
        env_file=str(_PROJECT_ROOT / ".env"),
        env_nested_delimiter="__",
        env_prefix="RESOLV_",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def get_settings() -> Settings:
    return Settings()
