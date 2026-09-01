import io
import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.api.chat import NO_INFORMATION, RetrievedChunk, compatible_chunks_query, keyword_terms, rank_retrieved_chunks
from app.services.bedrock_service import BedrockService
from app.services.indexing import is_compatible, reindex_document
from app.services.ai_provider import MockAIProvider


def settings(**values):
    return Settings(_env_file=None, admin_api_key="a" * 24, **values)


def test_provider_compatibility_includes_provider_model_and_dimensions():
    provider = MockAIProvider(settings())
    document = SimpleNamespace(
        indexing_status="indexed", embedding_provider="mock",
        embedding_model="mock-sha256-v1", embedding_dimensions=1024,
    )
    assert is_compatible(document, provider)
    for field, value in (("embedding_provider", "bedrock"), ("embedding_model", "other"), ("embedding_dimensions", 1536), ("indexing_status", "requires_reindex")):
        incompatible = SimpleNamespace(**document.__dict__)
        setattr(incompatible, field, value)
        assert not is_compatible(incompatible, provider)


def test_retrieval_query_excludes_incompatible_documents_before_distance():
    provider = MockAIProvider(settings())
    sql = str(compatible_chunks_query(provider).select().compile(compile_kwargs={"literal_binds": True}))
    assert "MATERIALIZED" in sql
    assert "documents.embedding_provider = 'mock'" in sql
    assert "documents.embedding_model = 'mock-sha256-v1'" in sql
    assert "documents.embedding_dimensions = 1024" in sql
    assert "documents.indexing_status = 'indexed'" in sql


def matching_chunks(question, chunks):
    terms = keyword_terms(question)
    candidates = []
    for filename, content, distance in chunks:
        folded = content.casefold()
        hits = sum(term in folded for term in terms)
        if distance < 0.70 or hits:
            candidates.append(RetrievedChunk(filename, content, distance, hits))
    return rank_retrieved_chunks(candidates, 5)


COMPANY_CHUNKS = [
    ("services.txt", "Acme provides managed cloud infrastructure and technical support.", 0.42),
    ("security.txt", "Our cyber resilience service protects businesses from ransomware attacks.", 0.66),
]


def test_direct_company_question_retrieves_company_information():
    results = matching_chunks("What services does the company provide?", COMPANY_CHUNKS)
    assert results[0].filename == "services.txt"


def test_differently_worded_ransomware_question_retrieves_security_service():
    results = matching_chunks("We need protection against ransomware. Which service should we discuss?", COMPANY_CHUNKS)
    assert results[0].filename == "security.txt"


def test_unrelated_question_has_no_retrieved_company_information():
    assert matching_chunks("What is the capital of France?", [
        (name, content, 0.91) for name, content, _ in COMPANY_CHUNKS
    ]) == []
    assert NO_INFORMATION == "I don't have that information in the available company documents."


def test_duplicate_chunks_are_removed_and_strongest_copy_is_kept():
    duplicate = "Our ransomware protection service is available."
    results = rank_retrieved_chunks([
        RetrievedChunk("older.txt", duplicate, 0.60, 1),
        RetrievedChunk("best.txt", "  OUR ransomware protection service is available.  ", 0.40, 1),
    ], 5)
    assert len(results) == 1
    assert results[0].filename == "best.txt"


def test_failed_reindex_does_not_modify_document_or_chunks():
    document = SimpleNamespace(filename="faq.txt", content=b"Enough original document text to index safely.", id="doc")
    provider = SimpleNamespace(provider_name="bedrock", embedding_model="model", embedding_dimensions=1024)
    provider.embed = lambda texts: (_ for _ in ()).throw(RuntimeError("provider unavailable"))
    db = SimpleNamespace(execute=lambda *args: (_ for _ in ()).throw(AssertionError("chunks must not be changed")))
    with pytest.raises(RuntimeError, match="provider unavailable"):
        reindex_document(db, document, provider)
    assert not hasattr(document, "embedding_provider")


class FakeBedrockClient:
    def __init__(self):
        self.invoke_calls = []
        self.converse_calls = []

    def invoke_model(self, **kwargs):
        self.invoke_calls.append(kwargs)
        dimensions = json.loads(kwargs["body"])["dimensions"]
        return {"body": io.BytesIO(json.dumps({"embedding": [0.0] * dimensions, "inputTextTokenCount": 3}).encode())}

    def converse(self, **kwargs):
        self.converse_calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": "Company answer"}]}}, "usage": {"inputTokens": 4, "outputTokens": 2}}


def approved_bedrock_provider(client):
    return BedrockService(settings(
        ai_provider_mode="bedrock", aws_region="ap-south-1",
        bedrock_chat_model_id="amazon.nova-micro-v1:0",
        bedrock_embedding_model_id="amazon.titan-embed-text-v2:0",
        bedrock_embedding_dimensions=1024,
    ), client=client)


def test_titan_embedding_request_and_response_parsing():
    client = FakeBedrockClient()
    provider = approved_bedrock_provider(client)
    vectors, tokens = provider.embed(["hello"])
    request = client.invoke_calls[0]
    body = json.loads(request["body"])
    assert len(vectors[0]) == 1024 and tokens == 3
    assert request["modelId"] == "amazon.titan-embed-text-v2:0"
    assert body == {"inputText": "hello", "dimensions": 1024, "normalize": True}


def test_nova_converse_request_and_response_parsing():
    client = FakeBedrockClient()
    provider = approved_bedrock_provider(client)
    answer, input_tokens, output_tokens = provider.answer("question", [], [("faq.txt", "context")])
    request = client.converse_calls[0]
    assert request["modelId"] == "amazon.nova-micro-v1:0"
    assert "context" in request["messages"][0]["content"][0]["text"]
    assert "COMPANY INFORMATION" in request["messages"][0]["content"][0]["text"]
    assert "Answer only using COMPANY INFORMATION" in request["system"][0]["text"]
    assert "invent services, prices, contacts, partners, certifications, policies" in request["system"][0]["text"]
    assert request["inferenceConfig"]["maxTokens"] == provider.settings.max_answer_tokens
    assert (answer, input_tokens, output_tokens) == ("Company answer", 4, 2)


def test_bedrock_provider_does_not_create_client_until_invoked(monkeypatch):
    monkeypatch.setattr("app.services.bedrock_service.boto3.client", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no client expected")))
    provider = BedrockService(settings(ai_provider_mode="bedrock"))
    assert provider.provider_name == "bedrock"
