"""Exception handlers.

Every error leaves the API in the same JSON shape:

    {"error": {"code": "...", "message": "...", "request_id": "...", "details": [...]}}

so clients (and the people reading CloudWatch logs) only have to handle one
format. Unexpected exceptions are logged with a stack trace but the client
only sees a generic 500, never internal details.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.repository import TaskNotFoundError

logger = logging.getLogger("app.errors")

_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    415: "unsupported_media_type",
    429: "too_many_requests",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": _request_id(request)}}
    if details:
        body["error"]["details"] = details
    response_headers = dict(headers or {})
    if rid := _request_id(request):
        response_headers["X-Request-ID"] = rid
    return JSONResponse(jsonable_encoder(body), status_code=status_code, headers=response_headers)


async def task_not_found_handler(request: Request, exc: TaskNotFoundError) -> JSONResponse:
    return error_response(request, status.HTTP_404_NOT_FOUND, "task_not_found", str(exc))


async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            # loc looks like ("body", "title") or ("query", "limit"); the first
            # part goes into "location", the rest is the field name.
            "field": ".".join(str(part) for part in err["loc"][1:]) or err["loc"][0],
            "location": err["loc"][0] if err["loc"] else None,
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    return error_response(
        request,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        "Request validation failed",
        details,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return error_response(
        request, exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None)
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TaskNotFoundError, task_not_found_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
