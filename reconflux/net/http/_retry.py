from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ParamSpec, TypeVar

import httpx
import tenacity


if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

Parameters = ParamSpec('Parameters')
ReturnValue = TypeVar('ReturnValue')


def is_retryable_httpx_exception(exception: BaseException) -> bool:
    if isinstance(
        exception,
        (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.CloseError,
            httpx.ProxyError,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
            httpx.LocalProtocolError,
        ),
    ):
        return True

    if isinstance(exception, httpx.HTTPStatusError):
        status_code = exception.response.status_code
        return status_code == 429 or 500 <= status_code <= 599

    return False


def httpx_retry(
    *,
    attempts: int = 4,
    min_wait_seconds: float = 0.5,
    max_wait_seconds: float = 8.0,
    reraise: bool = True,
) -> Callable[[Callable[Parameters, ReturnValue]], Callable[Parameters, ReturnValue]]:

    return tenacity.retry(
        retry=tenacity.retry_if_exception(is_retryable_httpx_exception),
        wait=tenacity.wait_exponential_jitter(
            initial=min_wait_seconds,
            max=max_wait_seconds,
        ),
        stop=tenacity.stop_after_attempt(attempts),
        reraise=reraise,
        before_sleep=tenacity.before_sleep_log(logger, log_level=logging.WARNING),
    )


def should_retry_response_status(response: httpx.Response) -> bool:
    return response.status_code == 429 or 500 <= response.status_code <= 599
