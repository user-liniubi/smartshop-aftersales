import os
from typing import Any

import httpx


class ApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class ApiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 30,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("SMARTSHOP_API_URL") or "http://127.0.0.1:8000"
        ).rstrip("/")
        self.token = token
        self.timeout = timeout

    def login(self, username: str, password: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/auth/login",
            json={"username": username, "password": password},
            include_auth=False,
        )

    def create_session(self) -> dict[str, Any]:
        return self._request("POST", "/chat/sessions")

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/chat/sessions")

    def get_messages(self, session_id: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/chat/sessions/{session_id}/messages")

    def get_order_by_number(self, order_no: str) -> dict[str, Any]:
        return self._request("GET", f"/orders/by-number/{order_no}")

    def list_my_orders(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._request("GET", f"/orders/mine?limit={limit}")

    def select_order(self, session_id: int, order_id: int) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/chat/sessions/{session_id}/order-selection",
            json={"order_id": order_id},
            timeout=120,
        )

    def send_message(self, session_id: int, content: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/chat/sessions/{session_id}/messages",
            json={"content": content},
            timeout=120,
        )

    def request_handoff(self, session_id: int, reason: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/chat/sessions/{session_id}/handoff",
            json={"reason": reason},
        )

    def list_my_after_sales_tickets(self) -> list[dict[str, Any]]:
        return self._request("GET", "/after-sales/tickets/mine")

    def get_after_sales_ticket_events(self, ticket_id: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/after-sales/tickets/{ticket_id}/events")

    def cancel_after_sales_ticket(self, ticket_id: int) -> dict[str, Any]:
        return self._request("POST", f"/after-sales/tickets/{ticket_id}/cancel")

    def list_pending_after_sales_tickets(self) -> list[dict[str, Any]]:
        return self._request("GET", "/agent/after-sales/tickets")

    def review_after_sales_ticket(
        self,
        ticket_id: int,
        *,
        decision: str,
        review_note: str = "",
        refund_amount: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision": decision,
            "review_note": review_note,
        }
        if refund_amount is not None:
            payload["refund_amount"] = refund_amount
        return self._request(
            "POST",
            f"/agent/after-sales/tickets/{ticket_id}/review",
            json=payload,
        )

    def list_failed_refund_executions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/agent/after-sales/refund-executions/failed")

    def retry_refund_execution(self, ticket_id: int) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/agent/after-sales/tickets/{ticket_id}/refund-execution/retry",
        )

    def list_products(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._request("GET", f"/agent/catalog/products?limit={limit}")

    def update_product(self, product_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/agent/catalog/products/{product_id}",
            json=payload,
        )

    def list_knowledge_documents(
        self,
        *,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        suffix = f"?category={category}" if category else ""
        return self._request("GET", f"/knowledge/documents{suffix}")

    def upload_knowledge_document(
        self,
        *,
        filename: str,
        payload: bytes,
        category: str,
        product_id: int | None = None,
    ) -> dict[str, Any]:
        data = {"category": category}
        if product_id is not None:
            data["product_id"] = str(product_id)
        return self._request(
            "POST",
            "/knowledge/upload",
            files={
                "file": (
                    filename,
                    payload,
                    "application/octet-stream",
                )
            },
            data=data,
            timeout=300,
        )

    def delete_knowledge_document(self, document_id: int) -> None:
        self._request("DELETE", f"/knowledge/documents/{document_id}")

    def update_knowledge_category(
        self,
        document_id: int,
        *,
        category: str,
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/knowledge/documents/{document_id}",
            json={"category": category},
        )

    def list_refund_authorization_rules(self) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/agent/after-sales/refund-authorization-rules",
        )

    def create_refund_authorization_rule(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/agent/after-sales/refund-authorization-rules",
            json=payload,
        )

    def update_refund_authorization_rule(
        self,
        rule_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/agent/after-sales/refund-authorization-rules/{rule_id}",
            json=payload,
        )

    def list_discount_rules(self) -> list[dict[str, Any]]:
        return self._request("GET", "/agent/discounts/rules")

    def create_discount_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/agent/discounts/rules", json=payload)

    def update_discount_rule(
        self,
        rule_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/agent/discounts/rules/{rule_id}",
            json=payload,
        )

    def list_config_audit_logs(self, limit: int = 30) -> list[dict[str, Any]]:
        return self._request("GET", f"/agent/config/audit-logs?limit={limit}")

    def list_pending_handoffs(self) -> list[dict[str, Any]]:
        return self._request("GET", "/agent/handoffs")

    def list_my_handoffs(self) -> list[dict[str, Any]]:
        return self._request("GET", "/agent/handoffs/mine")

    def claim_handoff(self, handoff_id: int) -> dict[str, Any]:
        return self._request("POST", f"/agent/handoffs/{handoff_id}/claim")

    def get_agent_session(self, session_id: int) -> dict[str, Any]:
        return self._request("GET", f"/agent/sessions/{session_id}")

    def reply_as_agent(self, session_id: int, content: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/agent/sessions/{session_id}/reply",
            json={"content": content},
        )

    def close_agent_session(self, session_id: int) -> dict[str, Any]:
        return self._request("POST", f"/agent/sessions/{session_id}/close")

    def _request(
        self,
        method: str,
        path: str,
        *,
        include_auth: bool = True,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        headers = kwargs.pop("headers", {})
        if include_auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=timeout or self.timeout,
            ) as client:
                response = client.request(
                    method,
                    path,
                    headers=headers,
                    **kwargs,
                )
        except httpx.HTTPError:
            raise ApiError("无法连接智能客服服务，请确认后端已经启动") from None

        if response.is_success:
            if response.status_code == 204 or not response.content:
                return None
            return response.json()

        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        raise ApiError(
            error.get("message") or "请求失败，请稍后重试",
            status_code=response.status_code,
            code=error.get("code"),
        )
