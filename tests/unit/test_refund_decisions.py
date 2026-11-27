import asyncio
import json

from sqlalchemy import select

from backend.app.models import Order
from backend.app.services.rag import RAGContext
from backend.app.services.refund_decisions import RefundDecisionService


class _FakeDecisionLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def propose_compensation(self, **kwargs) -> str:
        return json.dumps(self.payload)


def _rag_context() -> RAGContext:
    return RAGContext(
        evidence="[1] 轻微瑕疵可以根据商家授权协商补偿。",
        citations=[],
        chunks=(),
        grounded=True,
    )


def test_compensation_inside_authorization_is_auto_approved(
    seeded_client,
    test_database,
):
    with test_database.session_factory() as session:
        order = session.scalar(select(Order).where(Order.order_no == "A10086"))
        assert order is not None
        decision = asyncio.run(
            RefundDecisionService(
                session=session,
                llm=_FakeDecisionLLM(
                    {
                        "scenario_code": "cosmetic_minor",
                        "suggested_amount": 40,
                        "confidence": 0.92,
                        "analysis": "轻微瑕疵，建议补偿 40 元。",
                    }
                ),
            ).evaluate(
                order=order,
                issue_description="耳机有轻微划痕",
                rag_context=_rag_context(),
            )
        )

    assert decision.decision_status.value == "auto_approved"
    assert decision.suggested_amount == 40
    assert all(decision.validation.values())


def test_compensation_over_authorization_requires_manual_review(
    seeded_client,
    test_database,
):
    with test_database.session_factory() as session:
        order = session.scalar(select(Order).where(Order.order_no == "A10086"))
        assert order is not None
        decision = asyncio.run(
            RefundDecisionService(
                session=session,
                llm=_FakeDecisionLLM(
                    {
                        "scenario_code": "cosmetic_minor",
                        "suggested_amount": 500,
                        "confidence": 0.99,
                        "analysis": "要求高额补偿。",
                    }
                ),
            ).evaluate(
                order=order,
                issue_description="耳机有轻微划痕",
                rag_context=_rag_context(),
            )
        )

    assert decision.decision_status.value == "manual_review"
    assert decision.validation["within_authorization"] is False


def test_invalid_agent_decision_requires_manual_review(
    seeded_client,
    test_database,
):
    with test_database.session_factory() as session:
        order = session.scalar(select(Order).where(Order.order_no == "A10086"))
        assert order is not None
        decision = asyncio.run(
            RefundDecisionService(
                session=session,
                llm=_FakeDecisionLLM(
                    {
                        "scenario_code": "cosmetic_minor",
                        "suggested_amount": -1,
                        "confidence": 2,
                        "analysis": "",
                    }
                ),
            ).evaluate(
                order=order,
                issue_description="耳机有轻微划痕",
                rag_context=_rag_context(),
            )
        )

    assert decision.decision_status.value == "manual_review"
    assert decision.validation["agent_output_valid"] is False
