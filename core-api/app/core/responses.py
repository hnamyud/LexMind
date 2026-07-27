from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status_code: int, message: str, error: str | None = None):
        self.status_code = status_code
        self.message = message
        self.error = error or {
            400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 429: "Too Many Requests"
        }.get(status_code, "Internal Server Error")


def envelope(data: Any, message: str = "", status_code: int = 200) -> dict[str, Any]:
    return {"statusCode": status_code, "message": message, "data": data}


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"statusCode": exc.status_code, "message": exc.message, "error": exc.error})


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else exc.detail
    return JSONResponse(status_code=exc.status_code, content={"statusCode": exc.status_code, "message": message, "error": "Http Exception"})


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Preserve the established API validation contract: 400 instead of FastAPI's 422.
    messages = [error.get("msg", "Validation failed") for error in exc.errors()]
    return JSONResponse(status_code=400, content={"statusCode": 400, "message": messages, "error": "Bad Request"})
