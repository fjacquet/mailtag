"""API key authentication middleware for the MailTag webhook API."""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Paths that bypass authentication
PUBLIC_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key header on all requests except public paths."""

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != self.api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key", "error_code": "UNAUTHORIZED"},
            )
        return await call_next(request)
