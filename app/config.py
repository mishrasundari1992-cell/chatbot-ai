from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

STANDARD_EMBEDDING_DIMENSIONS = 1024


def parse_origins(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    ai_provider_mode: Literal["mock", "openai", "bedrock"] = "mock"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5.6-luna"
    embedding_model: str = "text-embedding-3-small"
    aws_region: str = "ap-south-1"
    bedrock_chat_model_id: str = "apac.amazon.nova-micro-v1:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    bedrock_embedding_dimensions: int = Field(1024, ge=1024, le=1024)
    bedrock_guardrail_id: str = ""
    bedrock_guardrail_version: str = ""
    database_url: str = "postgresql+psycopg://chatbot:local-development-only@localhost:5432/chatbot"
    admin_api_key: SecretStr = SecretStr("")
    allowed_origins: Annotated[list[str], NoDecode, BeforeValidator(parse_origins)] = ["http://localhost:8000"]
    max_upload_mb: int = Field(10, ge=1, le=100)
    max_context_chunks: int = Field(5, ge=1, le=20)
    retrieval_distance_threshold: float = Field(0.70, gt=0, le=2)
    monthly_token_limit: int = Field(1_000_000, ge=1)
    rate_limit_per_minute: int = Field(30, ge=1, le=1000)
    # Retained for compatibility with existing environments; providers always standardize to 1024.
    embedding_dimensions: int = Field(STANDARD_EMBEDDING_DIMENSIONS, ge=256, le=4096)
    max_answer_tokens: int = Field(500, ge=64, le=2000)
    max_resume_mb: int = Field(5, ge=1, le=10)
    hr_notification_email: str = "hrd@itsipl.com"
    support_phone: str = "+91-011-47695000"
    smtp_host: str = ""
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    @field_validator("admin_api_key")
    @classmethod
    def validate_admin_key(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if raw and len(raw) < 24:
            raise ValueError("ADMIN_API_KEY must be at least 24 characters")
        return value

    def validate_ai_provider(self) -> None:
        if self.ai_provider_mode == "openai" and not self.openai_api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER_MODE=openai")
        if self.ai_provider_mode == "bedrock":
            missing = [
                name for name, value in (
                    ("AWS_REGION", self.aws_region),
                    ("BEDROCK_CHAT_MODEL_ID", self.bedrock_chat_model_id),
                    ("BEDROCK_EMBEDDING_MODEL_ID", self.bedrock_embedding_model_id),
                ) if not value.strip()
            ]
            if missing:
                raise ValueError(f"Bedrock configuration is incomplete: {', '.join(missing)} required")
            if bool(self.bedrock_guardrail_id) != bool(self.bedrock_guardrail_version):
                raise ValueError("BEDROCK_GUARDRAIL_ID and BEDROCK_GUARDRAIL_VERSION must be configured together")


@lru_cache
def get_settings() -> Settings:
    return Settings()
