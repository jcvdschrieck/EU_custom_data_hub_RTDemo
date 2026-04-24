"""Starlette middleware that logs every API request to the api_log table."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from lib.database import write_api_log

_SKIP_ENDPOINTS = {"/health", "/docs", "/openapi.json", "/redoc"}


class ApiLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path in _SKIP_ENDPOINTS or path.startswith("/static"):
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        client_country = request.headers.get("X-Client-Country")
        records_returned = int(response.headers.get("X-Records-Returned", 0))

        try:
            write_api_log(
                timestamp=datetime.now(timezone.utc).isoformat(),
                method=request.method,
                endpoint=path,
                client_country=client_country,
                status_code=response.status_code,
                response_time_ms=round(elapsed_ms, 1),
                records_returned=records_returned,
            )
        except Exception:
            pass  # never let logging crash the API

        return response
