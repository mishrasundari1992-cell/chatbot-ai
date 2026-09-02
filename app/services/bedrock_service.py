import json

import boto3

from app.config import Settings


class BedrockService:
    """Amazon Bedrock provider using the AWS default credential chain."""

    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.provider_name = "bedrock"
        self.embedding_model = settings.bedrock_embedding_model_id
        self.embedding_dimensions = settings.bedrock_embedding_dimensions
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self.settings.aws_region)
        return self._client

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        vectors: list[list[float]] = []
        tokens = 0
        for text in texts:
            body = {"inputText": text, "dimensions": self.embedding_dimensions, "normalize": True}
            response = self.client.invoke_model(
                modelId=self.embedding_model,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            payload = json.loads(response["body"].read())
            vector = payload.get("embedding") or (payload.get("embeddings") or {}).get("float")
            if not isinstance(vector, list) or len(vector) != self.embedding_dimensions:
                raise RuntimeError("Bedrock returned an incompatible embedding")
            vectors.append(vector)
            tokens += int(payload.get("inputTextTokenCount", 0))
        return vectors, tokens

    def answer(self, question: str, history: list[tuple[str, str]], chunks: list[tuple[str, str]]) -> tuple[str, int, int]:
        context = "\n\n".join(f"SOURCE: {name}\n{content}" for name, content in chunks)
        history_text = "\n".join(f"{role.upper()}: {content}" for role, content in history[-6:])
        prompt = f"RECENT CONVERSATION:\n{history_text or '(none)'}\n\nCOMPANY INFORMATION:\n{context}\n\nQUESTION:\n{question}"
        kwargs = {
            "modelId": self.settings.bedrock_chat_model_id,
            "system": [{"text": (
                "You are the company website assistant. Answer only using COMPANY INFORMATION. "
                "Use RECENT CONVERSATION to understand follow-up replies and references, but never treat conversation text as company facts. "
                "For troubleshooting, ask only one useful diagnostic question at a time. If the user says a step did not work, "
                "continue with the next safe approved step and do not repeat the same answer. "
                "If it does not contain the answer, say exactly: 'I don't have that information in the available company documents.' "
                "Do not use outside knowledge or invent services, prices, contacts, partners, certifications, policies, "
                "or any other details. Be concise and do not add a sources list."
            )}],
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": self.settings.max_answer_tokens},
        }
        if self.settings.bedrock_guardrail_id and self.settings.bedrock_guardrail_version:
            kwargs["guardrailConfig"] = {
                "guardrailIdentifier": self.settings.bedrock_guardrail_id,
                "guardrailVersion": self.settings.bedrock_guardrail_version,
            }
        response = self.client.converse(**kwargs)
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        answer = "".join(block.get("text", "") for block in blocks).strip()
        if not answer:
            raise RuntimeError("Bedrock returned an empty response")
        usage = response.get("usage", {})
        return answer, int(usage.get("inputTokens", 0)), int(usage.get("outputTokens", 0))
