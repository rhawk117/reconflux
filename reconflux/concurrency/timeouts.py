from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import anyio

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@contextlib.contextmanager
def shielded_cancel_scope() -> Any:
    with anyio.CancelScope(shield=True) as cancel_scope:
        yield cancel_scope


class TimeSensitiveRunner[T]:
    def __init__(
        self,
        operation: Callable[..., Awaitable[T]],
        *operation_args: Any,
        **operation_kwargs: Any,
    ) -> None:
        self.operation: Callable[..., Awaitable[T]] = operation
        self.operation_args: tuple[Any, ...] = operation_args
        self.operation_kwargs = operation_kwargs

    async def fail_early(
        self,
        seconds: float,
        *,
        shield: bool = False,
    ) -> T:
        try:
            with anyio.fail_after(seconds, shield=shield):
                return await self.operation(*self.operation_args, **self.operation_kwargs)
        except TimeoutError:
            raise
        except BaseException as exc:
            cancelled_exception_class = anyio.get_cancelled_exc_class()
            if isinstance(exc, cancelled_exception_class):
                raise TimeoutError(
                    f'Operation timed out: {self.operation.__name__}'
                ) from exc
            raise

    async def move_on_after(self, seconds: float, *, shield: bool = False) -> T | None:
        with anyio.move_on_after(seconds, shield=shield) as cancel_scope:
            result = await self.operation(*self.operation_args, **self.operation_kwargs)

        if cancel_scope.cancelled_caught:
            return None

        return result


def current_effective_deadline() -> float:
    return anyio.current_effective_deadline()
