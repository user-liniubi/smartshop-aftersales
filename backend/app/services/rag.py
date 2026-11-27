import asyncio
import logging
import re
import time
from dataclasses import dataclass

from backend.app.core.config import Settings
from backend.app.models import KnowledgeCategory
from backend.app.rag.embeddings import BgeEmbeddingProvider
from backend.app.rag.vector_store import ChromaVectorStore, RetrievedChunk
from backend.app.schemas.rag import CitationResponse, RagAskResponse
from backend.app.services.llm import DeepSeekClient

NO_EVIDENCE_ANSWER = "当前知识库中没有足够依据确认这个问题，建议转人工客服进一步核实。"
_SENSITIVE_QUERY_PATTERNS = (
    re.compile(r"(列出|返回|查询|导出).{0,12}(全部|所有).{0,8}订单"),
    re.compile(r"(不要|无需|跳过|绕过).{0,8}(检查|校验).{0,8}(身份|权限)"),
)
logger = logging.getLogger(__name__)
_LEXICAL_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{2}|[A-Za-z0-9_-]{2,}")
_FILE_HINTS = {
    ("物流", "快递", "运单", "发货", "配送"): {
        "shipping_faq.md",
        "delivery_damage.md",
    },
    ("优惠", "折扣", "便宜", "活动价"): {"discount_policy.md"},
    ("退货", "退款", "七天无理由"): {"return_policy.md"},
    ("换货", "更换"): {"return_policy.md", "warranty_policy.md"},
    ("保修", "质保"): {"warranty_policy.md"},
    ("耳机", "降噪"): {
        "headphones_manual.md",
        "headphones_troubleshooting.md",
    },
    ("键盘", "机械"): {
        "keyboard_manual.md",
        "keyboard_troubleshooting.md",
    },
    ("显示器", "屏幕"): {
        "monitor_manual.md",
        "monitor_troubleshooting.md",
    },
    ("笔记本", "电脑"): {
        "laptop_manual.md",
        "laptop_troubleshooting.md",
    },
    ("鼠标",): {"mouse_manual.md", "mouse_troubleshooting.md"},
}


@dataclass(frozen=True)
class RAGContext:
    evidence: str
    citations: list[CitationResponse]
    chunks: tuple[RetrievedChunk, ...]
    grounded: bool


class RAGService:
    def __init__(
        self,
        *,
        settings: Settings,
        embedder: BgeEmbeddingProvider,
        vector_store: ChromaVectorStore,
        llm: DeepSeekClient,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.vector_store = vector_store
        self.llm = llm

    async def ask(
        self,
        *,
        question: str,
        product_id: int | None = None,
        top_k: int | None = None,
        category: KnowledgeCategory | None = None,
    ) -> RagAskResponse:
        context = await self.retrieve(
            question=question,
            product_id=product_id,
            top_k=top_k,
            categories=(category,) if category is not None else None,
        )

        if not context.grounded:
            return RagAskResponse(
                answer=NO_EVIDENCE_ANSWER,
                grounded=False,
                citations=[],
                model=self.settings.deepseek_model,
            )

        answer = await self.llm.generate_answer(
            question=question,
            evidence=context.evidence,
        )
        return RagAskResponse(
            answer=answer,
            grounded=True,
            citations=context.citations,
            model=self.settings.deepseek_model,
        )

    async def retrieve(
        self,
        *,
        question: str,
        product_id: int | None = None,
        top_k: int | None = None,
        category: KnowledgeCategory | None = None,
        categories: tuple[KnowledgeCategory, ...] | None = None,
    ) -> RAGContext:
        if category is not None:
            categories = (category,)
        return await asyncio.to_thread(
            self.retrieve_sync,
            question=question,
            product_id=product_id,
            top_k=top_k,
            categories=categories,
        )

    def retrieve_sync(
        self,
        *,
        question: str,
        product_id: int | None = None,
        top_k: int | None = None,
        categories: tuple[KnowledgeCategory, ...] | None = None,
    ) -> RAGContext:
        if is_sensitive_retrieval_query(question):
            logger.warning("RAG sensitive query refused before retrieval")
            return RAGContext(
                evidence="",
                citations=[],
                chunks=(),
                grounded=False,
            )

        started_at = time.perf_counter()
        query_embedding = self.embedder.embed_query(question)
        retrieved = self.vector_store.query(
            query_embedding,
            top_k=max((top_k or self.settings.rag_top_k) * 4, 20),
            product_id=product_id,
            categories=(
                tuple(category.value for category in categories) if categories is not None else None
            ),
        )
        logger.info(
            "RAG retrieval completed results=%d product_id=%s duration=%.3fs",
            len(retrieved),
            product_id,
            time.perf_counter() - started_at,
        )
        relevant = [
            chunk for chunk in retrieved if chunk.similarity >= self.settings.rag_min_similarity
        ]
        relevant = _rerank_chunks(
            question=question,
            chunks=relevant,
            limit=top_k or self.settings.rag_top_k,
        )
        citations = [self._to_citation(chunk, index) for index, chunk in enumerate(relevant, 1)]
        evidence = "\n\n".join(
            f"[{index}] 来源：{chunk.title}，{chunk.filename}"
            f"{self._location(chunk)}\n{chunk.content}"
            for index, chunk in enumerate(relevant, start=1)
        )
        return RAGContext(
            evidence=evidence,
            citations=citations,
            chunks=tuple(relevant),
            grounded=bool(relevant),
        )

    @staticmethod
    def _location(chunk: RetrievedChunk) -> str:
        location_parts: list[str] = []
        if chunk.heading:
            location_parts.append(chunk.heading)
        if chunk.page:
            location_parts.append(f"第 {chunk.page} 页")
        return f"，{'，'.join(location_parts)}" if location_parts else ""

    @staticmethod
    def _to_citation(chunk: RetrievedChunk, index: int) -> CitationResponse:
        excerpt = chunk.content if len(chunk.content) <= 240 else f"{chunk.content[:240]}..."
        return CitationResponse(
            document_id=chunk.document_id,
            chunk_id=f"[{index}] {chunk.vector_id}",
            filename=chunk.filename,
            title=chunk.title,
            category=KnowledgeCategory(chunk.category),
            page=chunk.page,
            heading=chunk.heading,
            excerpt=excerpt,
            similarity=round(chunk.similarity, 4),
        )


def is_sensitive_retrieval_query(question: str) -> bool:
    """Reject queries that ask to bypass identity or list cross-user orders."""

    return any(pattern.search(question) for pattern in _SENSITIVE_QUERY_PATTERNS)


def _rerank_chunks(
    *,
    question: str,
    chunks: list[RetrievedChunk],
    limit: int,
) -> list[RetrievedChunk]:
    terms = {
        match.group(0).lower()
        for match in _LEXICAL_TOKEN_PATTERN.finditer(question)
        if match.group(0).strip()
    }
    if not terms:
        return chunks[:limit]

    def rank(chunk: RetrievedChunk) -> float:
        searchable = " ".join(
            [
                chunk.title,
                chunk.heading or "",
                chunk.filename,
                chunk.content,
            ]
        ).lower()
        overlap = sum(1 for term in terms if term in searchable)
        exact_title_bonus = 0.04 if any(term in chunk.title.lower() for term in terms) else 0
        file_hint_bonus = min(
            sum(
                (0.14 if chunk.filename in filenames else 0)
                for keywords, filenames in _FILE_HINTS.items()
                if any(keyword in question for keyword in keywords)
            ),
            0.3,
        )
        return chunk.similarity + min(overlap * 0.035, 0.21) + exact_title_bonus + file_hint_bonus

    ranked = sorted(chunks, key=rank, reverse=True)
    selected: list[RetrievedChunk] = []
    selected_documents: set[int] = set()
    deferred: list[RetrievedChunk] = []
    for chunk in ranked:
        if chunk.document_id not in selected_documents:
            selected.append(chunk)
            selected_documents.add(chunk.document_id)
        else:
            deferred.append(chunk)
        if len(selected) == limit:
            return selected
    return (selected + deferred)[:limit]
