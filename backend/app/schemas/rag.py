from pydantic import BaseModel, Field

from backend.app.models.enums import KnowledgeCategory


class RagAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    product_id: int | None = Field(default=None, gt=0)
    top_k: int | None = Field(default=None, ge=1, le=10)
    category: KnowledgeCategory | None = None


class CitationResponse(BaseModel):
    document_id: int
    chunk_id: str
    filename: str
    title: str
    category: KnowledgeCategory | None = None
    page: int | None = None
    heading: str | None = None
    excerpt: str
    similarity: float


class RagAskResponse(BaseModel):
    answer: str
    grounded: bool
    citations: list[CitationResponse]
    model: str
