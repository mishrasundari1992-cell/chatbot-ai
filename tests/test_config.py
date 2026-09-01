import os

import pytest

from app.config import Settings
from app.services.ai_provider import AIConfigurationError, MockAIProvider, get_ai_provider


def test_comma_separated_origins():
    settings = Settings(_env_file=None, allowed_origins="https://one.example, https://two.example", admin_api_key="a" * 24)
    assert settings.allowed_origins == ["https://one.example", "https://two.example"]


def test_mock_is_default_and_needs_no_key():
    settings = Settings(_env_file=None, openai_api_key="", admin_api_key="a" * 24)
    assert settings.ai_provider_mode == "mock"
    assert isinstance(get_ai_provider(settings), MockAIProvider)
    assert get_ai_provider(settings).embedding_dimensions == 1024


def test_verified_apac_bedrock_defaults():
    settings = Settings(_env_file=None, admin_api_key="a" * 24)
    assert settings.aws_region == "ap-south-1"
    assert settings.bedrock_chat_model_id == "apac.amazon.nova-micro-v1:0"
    assert settings.bedrock_embedding_model_id == "amazon.titan-embed-text-v2:0"
    assert settings.bedrock_embedding_dimensions == 1024


def test_retrieval_threshold_default_and_environment_override(monkeypatch):
    assert Settings(_env_file=None, admin_api_key="a" * 24).retrieval_distance_threshold == 0.70
    monkeypatch.setenv("RETRIEVAL_DISTANCE_THRESHOLD", "0.82")
    assert Settings(_env_file=None, admin_api_key="a" * 24).retrieval_distance_threshold == 0.82


def test_pytest_environment_forces_hermetic_mock_ai_configuration():
    assert os.environ["AI_PROVIDER_MODE"] == "mock"
    assert os.environ["OPENAI_API_KEY"] == ""
    assert os.environ["EMBEDDING_DIMENSIONS"] == "1024"
    assert os.environ["BEDROCK_EMBEDDING_DIMENSIONS"] == "1024"
    assert os.environ["ADMIN_API_KEY"] == "test-admin-api-key-at-least-24"


def test_mock_response_uses_retrieved_document_text():
    provider = MockAIProvider(Settings(_env_file=None, admin_api_key="a" * 24))
    answer, input_tokens, output_tokens = provider.answer("What?", [], [("faq.txt", "We provide local support.")])
    assert "Mock mode" in answer
    assert "We provide local support." in answer
    assert (input_tokens, output_tokens) == (0, 0)


def test_openai_mode_without_key_has_safe_configuration_error():
    settings = Settings(_env_file=None, ai_provider_mode="openai", openai_api_key="", admin_api_key="a" * 24)
    try:
        get_ai_provider(settings)
    except AIConfigurationError as exc:
        assert str(exc) == "OPENAI_API_KEY is required when AI_PROVIDER_MODE=openai"
    else:
        raise AssertionError("Expected a configuration error")


def test_openai_mode_uses_ready_integration_when_key_is_present(monkeypatch):
    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("app.services.openai_service.OpenAI", FakeOpenAI)
    settings = Settings(_env_file=None, ai_provider_mode="openai", openai_api_key="configured-later", admin_api_key="a" * 24)
    provider = get_ai_provider(settings)
    assert provider.__class__.__name__ == "OpenAIService"
    assert provider.embedding_dimensions == 1024


def test_bedrock_mode_reports_all_missing_configuration():
    settings = Settings(
        _env_file=None, ai_provider_mode="bedrock", aws_region="", bedrock_chat_model_id="",
        bedrock_embedding_model_id="", admin_api_key="a" * 24,
    )
    with pytest.raises(AIConfigurationError, match="AWS_REGION.*BEDROCK_CHAT_MODEL_ID.*BEDROCK_EMBEDDING_MODEL_ID"):
        get_ai_provider(settings)


def test_bedrock_guardrail_configuration_must_be_complete():
    settings = Settings(
        _env_file=None, ai_provider_mode="bedrock", aws_region="ap-south-1",
        bedrock_chat_model_id="chat", bedrock_embedding_model_id="embed",
        bedrock_guardrail_id="guardrail", bedrock_guardrail_version="", admin_api_key="a" * 24,
    )
    with pytest.raises(AIConfigurationError, match="must be configured together"):
        get_ai_provider(settings)
