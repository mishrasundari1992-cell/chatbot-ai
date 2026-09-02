import json
import re
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.main_state import limiter
from app.models import Conversation, Document, DocumentChunk, Message
from app.schemas import ChatRequest, ChatResponse
from app.services.ai_provider import AIConfigurationError, get_ai_provider
from app.services.usage import month_usage, record_usage

router = APIRouter(prefix="/api/chat", tags=["chat"])
NO_INFORMATION = "I don't have that information in the available company documents."
KEYWORD_STOP_WORDS = {
    "about", "against", "available", "company", "could", "discuss", "does", "documents",
    "from", "have", "information", "need", "please", "should", "that", "their", "there",
    "these", "they", "this", "what", "when", "where", "which", "with", "would", "your",
}
FOLLOW_UP_PATTERN = re.compile(
    r"\b(it|that|this|same|still|again|yes|no|worked|working|error|issue|problem|now|then)\b",
    re.IGNORECASE,
)
ACKNOWLEDGEMENT_PATTERN = re.compile(r"^(yes|no|ok|okay|same|still|again|not working|it is not working)[.! ]*$", re.IGNORECASE)


@dataclass(frozen=True)
class RetrievedChunk:
    filename: str
    content: str
    distance: float
    keyword_hits: int = 0


def keyword_terms(question: str) -> list[str]:
    """Return useful, unique terms for a small case-insensitive lexical search."""
    terms: list[str] = []
    for term in re.findall(r"[a-z0-9]+", question.casefold()):
        if len(term) >= 4 and term not in KEYWORD_STOP_WORDS and term not in terms:
            terms.append(term)
    return terms[:12]


def build_retrieval_query(question: str, history: list[tuple[str, str]]) -> str:
    """Attach the recent customer issue when a message is an ambiguous follow-up."""
    words = re.findall(r"[a-z0-9]+", question.casefold())
    needs_context = len(words) <= 8 or bool(FOLLOW_UP_PATTERN.search(question))
    if not needs_context:
        return question
    prior_user_messages = [
        content.strip() for role, content in reversed(history)
        if role == "user" and content.strip() and not ACKNOWLEDGEMENT_PATTERN.fullmatch(content.strip())
    ][:2]
    if not prior_user_messages:
        return question
    prior_user_messages.reverse()
    return f"Previous customer issue: {' | '.join(prior_user_messages)}\nCurrent follow-up: {question}"


def rank_retrieved_chunks(
    candidates: list[RetrievedChunk], max_chunks: int,
) -> list[RetrievedChunk]:
    """Remove repeated content and rank combined lexical/semantic matches."""
    strongest: dict[str, RetrievedChunk] = {}
    for candidate in candidates:
        duplicate_key = " ".join(candidate.content.casefold().split())
        current = strongest.get(duplicate_key)
        candidate_score = candidate.keyword_hits * 0.25 + (1.0 - candidate.distance)
        current_score = current.keyword_hits * 0.25 + (1.0 - current.distance) if current else float("-inf")
        if candidate_score > current_score:
            strongest[duplicate_key] = candidate
    return sorted(
        strongest.values(),
        key=lambda item: (-(item.keyword_hits * 0.25 + (1.0 - item.distance)), item.distance, item.filename),
    )[:max_chunks]


def compatible_chunks_query(service):
    """Materialize identity-compatible vectors before any distance operation."""
    return (
        select(DocumentChunk.content, DocumentChunk.embedding, Document.filename)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.indexing_status == "indexed",
            Document.embedding_provider == service.provider_name,
            Document.embedding_model == service.embedding_model,
            Document.embedding_dimensions == service.embedding_dimensions,
        )
        .cte("compatible_chunks")
        .prefix_with("MATERIALIZED")
    )


def retrieve_chunks(db: Session, service, embedding: list[float], question: str, settings) -> list[RetrievedChunk]:
    compatible_chunks = compatible_chunks_query(service)
    distance = compatible_chunks.c.embedding.cosine_distance(embedding).label("distance")
    candidate_limit = settings.max_context_chunks * 4
    candidates: list[RetrievedChunk] = []

    semantic_rows = db.execute(
        select(compatible_chunks.c.content, compatible_chunks.c.filename, distance)
        .where(distance < settings.retrieval_distance_threshold)
        .order_by(distance)
        .limit(candidate_limit)
    ).all()
    candidates.extend(RetrievedChunk(row.filename, row.content, float(row.distance), 0) for row in semantic_rows)

    terms = keyword_terms(question)
    if terms:
        matches = [compatible_chunks.c.content.ilike(f"%{term}%") for term in terms]
        keyword_hits = sum((case((match, 1), else_=0) for match in matches), start=0).label("keyword_hits")
        keyword_rows = db.execute(
            select(compatible_chunks.c.content, compatible_chunks.c.filename, distance, keyword_hits)
            .where(or_(*matches))
            .order_by(keyword_hits.desc(), distance)
            .limit(candidate_limit)
        ).all()
        candidates.extend(
            RetrievedChunk(row.filename, row.content, float(row.distance), int(row.keyword_hits))
            for row in keyword_rows
        )
    return rank_retrieved_chunks(candidates, settings.max_context_chunks)


@router.post("", response_model=ChatResponse)
@limiter.limit(lambda: f"{get_settings().rate_limit_per_minute}/minute")
def chat(request: Request, payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    settings = get_settings()
    conversation = db.get(Conversation, payload.conversation_id) if payload.conversation_id else None
    if payload.conversation_id and not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation is None:
        conversation = Conversation()
        db.add(conversation)
        db.flush()
    if settings.ai_provider_mode == "openai" and month_usage(db) >= settings.monthly_token_limit:
        raise HTTPException(status_code=429, detail="Monthly OpenAI usage limit reached")
    history_rows = db.execute(select(Message.role, Message.content).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(8)).all()
    history = list(reversed(history_rows))
    retrieval_query = build_retrieval_query(payload.message, history)
    try:
        service = get_ai_provider(settings)
        vectors, embedding_tokens = service.embed([retrieval_query])
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Chat service is temporarily unavailable") from exc
    rows = retrieve_chunks(db, service, vectors[0], retrieval_query, settings)
    sources = list(dict.fromkeys(row.filename for row in rows))
    if rows:
        try:
            answer, input_tokens, output_tokens = service.answer(payload.message, history, [(row.filename, row.content) for row in rows])
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Chat service is temporarily unavailable") from exc
    else:
        answer = NO_INFORMATION
        input_tokens = output_tokens = 0
    db.add(Message(conversation_id=conversation.id, role="user", content=payload.message))
    db.add(Message(conversation_id=conversation.id, role="assistant", content=answer, sources=json.dumps(sources)))
    record_usage(db, embedding_tokens + input_tokens, output_tokens)
    db.commit()
    return ChatResponse(conversation_id=conversation.id, answer=answer, sources=sources)
