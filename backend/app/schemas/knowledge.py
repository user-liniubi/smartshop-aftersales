from datetime import datetime

from pydantic import BaseModel, ConfigDict

from backend.app.models.enums import (
    IngestionJobStatus,
    KnowledgeCategory,
    KnowledgeDocumentStatus,
)


class KnowledgeDocumentResponse(BaseModel):
    id: int
    product_id: int | None
    filename: str
    title: str
    source_type: str
    category: KnowledgeCategory
    status: KnowledgeDocumentStatus
    version: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KnowledgeUploadResponse(BaseModel):
    document: KnowledgeDocumentResponse
    chunk_count: int
    duplicate: bool = False


class KnowledgeCategoryUpdate(BaseModel):
    category: KnowledgeCategory


class IngestionJobResponse(BaseModel):
    task_id: str
    document_id: int | None
    filename: str
    product_id: int | None
    category: KnowledgeCategory
    status: IngestionJobStatus
    progress: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AsyncKnowledgeUploadResponse(BaseModel):
    task_id: str
    status: IngestionJobStatus
