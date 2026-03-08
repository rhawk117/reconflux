from __future__ import annotations

import dataclasses as dc
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import anyio
from anyio import CapacityLimiter

from reconflux.concurrency.limiter import acquire_limiter
from reconflux.core import DataclassMixin

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping


class ExecutionMode(StrEnum):
    FAIL_FAST = 'fail_fast'
    BEST_EFFORT = 'best_effort'


@dc.dataclass(slots=True)
class TaskFailure:
    task_name: str
    exception: BaseException

@dc.dataclass(slots=True)
class ConcurrentResults[T](DataclassMixin):
    values: dict[str, T] = dc.field(default_factory=dict)
    failures: dict[str, str] = dc.field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return not self.failures

type AwaitableCallback[T] = Callable[[], Awaitable[T]]


async def run_concurrently(
    operations: Mapping[str, AwaitableCallback[Any]],
) -> None:
    async with anyio.create_task_group() as task_group:
        for operation_name, operation in operations.items():
            task_group.start_soon(
                operation,
                name=operation_name,
            )


async def collect_concurrently[T](
    operations: Mapping[str, AwaitableCallback[T]],
    *,
    execution_mode: ExecutionMode = ExecutionMode.FAIL_FAST,
) -> ConcurrentResults[T]:
    results: dict[str, T] = {}
    failures: dict[str, str] = {}

    async def runner(
        operation_name: str,
        operation: Callable[[], Awaitable[T]],
    ) -> None:
        try:
            results[operation_name] = await operation()
        except BaseException as exc:
            if execution_mode == ExecutionMode.FAIL_FAST:
                raise

            failures[operation_name] = repr(exc)

    async with anyio.create_task_group() as task_group:
        for operation_name, operation in operations.items():
            task_group.start_soon(
                runner,
                operation_name,
                operation,
                name=operation_name,
            )

    return ConcurrentResults(
        values=results,
        failures=failures,
    )


async def map_concurrently[TInput, TResult](
    values: Iterable[TInput],
    operation: Callable[[TInput], Awaitable[TResult]],
    *,
    execution_mode: ExecutionMode = ExecutionMode.FAIL_FAST,
    limiter: CapacityLimiter | str | None = None,
    name_builder: Callable[[TInput], str] | None = None,
) -> ConcurrentResults[TResult]:
    value_list = list(values)
    results: dict[str, TResult] = {}
    failures: dict[str, str] = {}

    async def runner(value: TInput) -> None:
        task_name = name_builder(value) if name_builder is not None else str(value)

        try:
            if limiter is None:
                result = await operation(value)
            else:
                async with acquire_limiter(limiter):
                    result = await operation(value)

            results[task_name] = result
        except BaseException as exc:
            if execution_mode == ExecutionMode.FAIL_FAST:
                raise

            failures[task_name] = repr(exc)

    async with anyio.create_task_group() as task_group:
        for value in value_list:
            task_name = name_builder(value) if name_builder is not None else str(value)
            task_group.start_soon(
                runner,
                value,
                name=task_name,
            )

    return ConcurrentResults(
        values=results,
        failures=failures,
    )
