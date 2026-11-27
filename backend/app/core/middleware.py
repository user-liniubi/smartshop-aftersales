import logging
import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.app.core.request_context import (
    reset_request_id,
    set_request_id,
)

logger = logging.getLogger(__name__)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,80}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID and log one safe request summary."""

    async def dispatch(self, request: Request, call_next) -> Response:
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_request_id
            if _SAFE_REQUEST_ID.fullmatch(supplied_request_id)
            else uuid.uuid4().hex
        )
        token = set_request_id(request_id)
        request.state.request_id = request_id
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request failed method=%s path=%s",
                request.method,
                request.url.path,
            )
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            if "response" in locals():
                logger.info(
                    "request completed method=%s path=%s status=%s duration_ms=%.2f",
                    request.method,
                    request.url.path,
                    response.status_code,
                    elapsed_ms,
                )
            reset_request_id(token)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
        return response
