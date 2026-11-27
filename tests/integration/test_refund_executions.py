from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.core.exceptions import AppError
from backend.app.models import (
    AfterSalesTicket,
    AfterSalesTicketEvent,
    AgentDecision,
    ChatMessage,
    ChatSession,
    Order,
    RefundExecution,
    User,
)
from backend.app.models.enums import (
    AfterSalesTicketStatus,
    AfterSalesTicketType,
    AgentDecisionStatus,
    RefundExecutionStatus,
)
from backend.app.services.after_sales_eligibility import AfterSalesEligibilityService
from backend.app.services.after_sales_tickets import AfterSalesTicketService
from backend.app.services.refund_decisions import RefundDecision
from backend.app.services.refund_executions import (
    RefundExecutionService,
    RefundGatewayResult,
)
from sample_data.seed import AGENT_PASSWORD


def _login_headers(client, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_manual_compensation_ticket(
    session,
    *,
    user_id: int,
    order: Order,
    suggested_amount: Decimal = Decimal("40.00"),
) -> tuple[AfterSalesTicket, AgentDecision]:
    chat_session = ChatSession(user_id=user_id, intent="compensation_request")
    session.add(chat_session)
    session.flush()
    eligibility = AfterSalesEligibilityService().evaluate(
        order=order,
        request_type=AfterSalesTicketType.COMPENSATION.value,
        issue_description="商品有轻微划痕",
    )
    decision = RefundDecision(
        scenario_code="cosmetic_minor",
        rule_version=1,
        authorization_min=Decimal("0.00"),
        authorization_max=Decimal("50.00"),
        suggested_amount=suggested_amount,
        available_amount=order.paid_amount,
        confidence=Decimal("0.70"),
        analysis="置信度不足，转人工审核。",
        validation={"confidence_reached": False},
        decision_status=AgentDecisionStatus.MANUAL_REVIEW,
    )
    ticket, agent_decision, auto_approved = AfterSalesTicketService(
        session
    ).create_compensation_for_session(
        chat_session=chat_session,
        order=order,
        issue_description="商品有轻微划痕",
        citations=[],
        eligibility=eligibility,
        decision=decision,
    )
    assert auto_approved is False
    return ticket, agent_decision


def test_manual_compensation_approval_persists_final_amount_and_executes(
    seeded_client,
    test_database,
):
    with test_database.session_factory() as session:
        user = session.scalar(select(User).where(User.username == "consumer_demo"))
        order = session.scalar(select(Order).where(Order.order_no == "A10086"))
        assert user is not None
        assert order is not None
        ticket, _ = _create_manual_compensation_ticket(
            session,
            user_id=user.id,
            order=order,
        )
        ticket_id = ticket.id

    agent_headers = _login_headers(seeded_client, "agent_demo", AGENT_PASSWORD)
    response = seeded_client.post(
        f"/agent/after-sales/tickets/{ticket_id}/review",
        headers=agent_headers,
        json={
            "decision": "approved",
            "review_note": "人工将补偿金额调整为 60 元",
            "refund_amount": "60.00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approved"
    assert payload["refund_amount"] == "60.00"
    assert payload["agent_decision"]["decision_status"] == "manually_approved"
    assert payload["refund_execution"]["status"] == "success"
    assert payload["refund_execution"]["amount"] == "60.00"

    with test_database.session_factory() as session:
        decision = session.scalar(select(AgentDecision).where(AgentDecision.ticket_id == ticket_id))
        execution = session.scalar(
            select(RefundExecution).where(RefundExecution.ticket_id == ticket_id)
        )
        assert decision is not None
        assert decision.decision_status == "manually_approved"
        assert execution is not None
        assert execution.amount == Decimal("60.00")
        assert execution.status == "success"
        assert execution.idempotency_key.startswith("after-sales:")


def test_manual_approval_cannot_exceed_remaining_refund_balance(
    seeded_client,
    test_database,
):
    with test_database.session_factory() as session:
        user = session.scalar(select(User).where(User.username == "consumer_demo"))
        order = session.scalar(select(Order).where(Order.order_no == "A10086"))
        assert user is not None
        assert order is not None
        ticket, _ = _create_manual_compensation_ticket(
            session,
            user_id=user.id,
            order=order,
            suggested_amount=Decimal("10.00"),
        )
        ticket_id = ticket.id

    agent_headers = _login_headers(seeded_client, "agent_demo", AGENT_PASSWORD)
    response = seeded_client.post(
        f"/agent/after-sales/tickets/{ticket_id}/review",
        headers=agent_headers,
        json={
            "decision": "approved",
            "review_note": "尝试超额补偿",
            "refund_amount": "900.00",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "refund_exceeds_available_balance"
    assert response.json()["error"]["details"]["available_amount"] == "899.00"
    with test_database.session_factory() as session:
        ticket = session.get(AfterSalesTicket, ticket_id)
        decision = session.scalar(select(AgentDecision).where(AgentDecision.ticket_id == ticket_id))
        execution = session.scalar(
            select(RefundExecution).where(RefundExecution.ticket_id == ticket_id)
        )
        assert ticket is not None
        assert ticket.status == "pending_approval"
        assert ticket.refund_amount is None
        assert decision is not None
        assert decision.decision_status == "manual_review"
        assert execution is None


def test_previous_approved_refund_reduces_available_balance(
    seeded_client,
    test_database,
):
    with test_database.session_factory() as session:
        user = session.scalar(select(User).where(User.username == "consumer_demo"))
        order = session.scalar(select(Order).where(Order.order_no == "A10086"))
        assert user is not None
        assert order is not None
        return_session = ChatSession(user_id=user.id, intent="return_request")
        session.add(return_session)
        session.flush()
        return_ticket, _ = AfterSalesTicketService(session).create_for_session(
            chat_session=return_session,
            order=order,
            request_type=AfterSalesTicketType.RETURN,
            issue_description="左耳没有声音，申请退货",
            citations=[],
        )
        first_ticket_id = return_ticket.id

    agent_headers = _login_headers(seeded_client, "agent_demo", AGENT_PASSWORD)
    first_review = seeded_client.post(
        f"/agent/after-sales/tickets/{first_ticket_id}/review",
        headers=agent_headers,
        json={"decision": "approved", "review_note": "全额退款审批通过"},
    )
    assert first_review.status_code == 200

    with test_database.session_factory() as session:
        user = session.scalar(select(User).where(User.username == "consumer_demo"))
        order = session.scalar(select(Order).where(Order.order_no == "A10086"))
        assert user is not None
        assert order is not None
        compensation, _ = _create_manual_compensation_ticket(
            session,
            user_id=user.id,
            order=order,
            suggested_amount=Decimal("10.00"),
        )
        compensation_id = compensation.id

    second_review = seeded_client.post(
        f"/agent/after-sales/tickets/{compensation_id}/review",
        headers=agent_headers,
        json={
            "decision": "approved",
            "review_note": "尝试二次补偿",
            "refund_amount": "10.00",
        },
    )
    assert second_review.status_code == 409
    assert second_review.json()["error"]["code"] == "refund_exceeds_available_balance"
    assert second_review.json()["error"]["details"]["available_amount"] == "0.00"


class _FlakyGateway:
    name = "flaky-test"

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *, idempotency_key, amount, currency) -> RefundGatewayResult:
        self.calls += 1
        if self.calls == 1:
            return RefundGatewayResult(
                success=False,
                failure_code="temporary_failure",
                failure_message="模拟临时失败",
            )
        return RefundGatewayResult(
            success=True,
            provider_reference=f"RETRY-{self.calls}",
        )


class _AlwaysFailingGateway:
    name = "always-failing-test"

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *, idempotency_key, amount, currency) -> RefundGatewayResult:
        self.calls += 1
        return RefundGatewayResult(
            success=False,
            failure_code="provider_down",
            failure_message="模拟退款通道不可用",
        )


def _create_approved_ticket(session, *, suffix: str, amount: Decimal) -> int:
    user = session.scalar(select(User).where(User.username == "consumer_demo"))
    order = session.scalar(select(Order).where(Order.order_no == "A10086"))
    assert user is not None
    assert order is not None
    chat_session = ChatSession(user_id=user.id, intent="compensation_request")
    session.add(chat_session)
    session.flush()
    ticket = AfterSalesTicket(
        ticket_no=f"AS-{suffix}",
        session_id=chat_session.id,
        user_id=user.id,
        order_id=order.id,
        request_type=AfterSalesTicketType.COMPENSATION.value,
        issue_description="退款执行测试",
        refund_amount=amount,
        currency="CNY",
        status=AfterSalesTicketStatus.APPROVED.value,
    )
    session.add(ticket)
    session.commit()
    return ticket.id


def test_refund_execution_is_idempotent_and_retries_temporary_failure(
    seeded_client,
    test_database,
):
    gateway = _FlakyGateway()
    with test_database.session_factory() as session:
        ticket_id = _create_approved_ticket(
            session,
            suffix="FLAKY000001",
            amount=Decimal("25.00"),
        )
        service = RefundExecutionService(session, gateway=gateway)
        first = service.execute_for_ticket(ticket_id=ticket_id)
        assert first.status == RefundExecutionStatus.FAILED.value
        assert first.attempt_count == 1

        retried = service.execute_for_ticket(ticket_id=ticket_id, retry_failed=True)
        assert retried.status == RefundExecutionStatus.SUCCESS.value
        assert retried.attempt_count == 2
        assert retried.provider_reference == "RETRY-2"

        unchanged = service.execute_for_ticket(ticket_id=ticket_id, retry_failed=True)
        assert unchanged.id == retried.id
        assert unchanged.provider_reference == retried.provider_reference
        assert gateway.calls == 2

        events = list(
            session.scalars(
                select(AfterSalesTicketEvent).where(AfterSalesTicketEvent.ticket_id == ticket_id)
            )
        )
        messages = list(
            session.scalars(select(ChatMessage).where(ChatMessage.sender_type == "system"))
        )
    assert [event.event_type for event in events] == ["system_note", "system_note"]
    assert len(messages) == 2
    assert execution_count(test_database, ticket_id) == 1


def test_refund_retry_stops_at_configured_limit(seeded_client, test_database):
    gateway = _AlwaysFailingGateway()
    with test_database.session_factory() as session:
        ticket_id = _create_approved_ticket(
            session,
            suffix="FAILED000001",
            amount=Decimal("20.00"),
        )
        service = RefundExecutionService(
            session,
            gateway=gateway,
            max_attempts=3,
        )
        assert service.execute_for_ticket(ticket_id=ticket_id).attempt_count == 1
        assert service.execute_for_ticket(ticket_id=ticket_id, retry_failed=True).attempt_count == 2
        assert service.execute_for_ticket(ticket_id=ticket_id, retry_failed=True).attempt_count == 3
        with pytest.raises(AppError) as error:
            service.execute_for_ticket(ticket_id=ticket_id, retry_failed=True)

    assert error.value.code == "refund_retry_exhausted"
    assert gateway.calls == 3


def test_agent_can_list_and_retry_failed_execution(
    seeded_client,
    test_database,
):
    with test_database.session_factory() as session:
        ticket_id = _create_approved_ticket(
            session,
            suffix="RETRYAPI0001",
            amount=Decimal("15.00"),
        )
        ticket = session.get(AfterSalesTicket, ticket_id)
        assert ticket is not None
        session.add(
            RefundExecution(
                ticket_id=ticket.id,
                idempotency_key=f"after-sales:{ticket.ticket_no}:refund:v1",
                amount=ticket.refund_amount,
                currency=ticket.currency,
                status=RefundExecutionStatus.FAILED.value,
                attempt_count=1,
                provider="failed-test",
                failure_code="provider_down",
                failure_message="模拟退款通道不可用",
            )
        )
        session.commit()

    agent_headers = _login_headers(seeded_client, "agent_demo", AGENT_PASSWORD)
    failed = seeded_client.get(
        "/agent/after-sales/refund-executions/failed",
        headers=agent_headers,
    )
    retried = seeded_client.post(
        f"/agent/after-sales/tickets/{ticket_id}/refund-execution/retry",
        headers=agent_headers,
    )
    failed_after = seeded_client.get(
        "/agent/after-sales/refund-executions/failed",
        headers=agent_headers,
    )

    assert failed.status_code == 200
    assert failed.json()[0]["ticket_id"] == ticket_id
    assert retried.status_code == 200
    assert retried.json()["status"] == "success"
    assert retried.json()["attempt_count"] == 2
    assert failed_after.json() == []


def execution_count(test_database, ticket_id: int) -> int:
    with test_database.session_factory() as session:
        return len(
            list(
                session.scalars(
                    select(RefundExecution).where(RefundExecution.ticket_id == ticket_id)
                )
            )
        )
