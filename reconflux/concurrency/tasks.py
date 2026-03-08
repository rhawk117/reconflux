from __future__ import annotations

import abc
import dataclasses as dc
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import anyio
from anyio import CapacityLimiter

from reconflux.concurrency.limiter import acquire_limiter
from reconflux.core import DataclassMixin, emit_internal_warning

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

    def stringify_warnings(self) -> str:
        warnings = [
            f'{task_name}: {message}' for task_name, message in self.failures.items()
        ]
        return '\n'.join(warnings)


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


class DispatchableTask[T](abc.ABC):
    @abc.abstractmethod
    def get_task_name(self) -> str: ...

    @abc.abstractmethod
    async def __call__(self) -> T: ...


async def dispatch_tasks[T](
    tasks: Iterable[DispatchableTask[T]],
    *,
    execution_mode: ExecutionMode = ExecutionMode.FAIL_FAST,
    limiter: CapacityLimiter | str | None = None,
) -> ConcurrentResults[T]:
    results: dict[str, T] = {}
    failures: dict[str, str] = {}

    async def runner(task: DispatchableTask[T]) -> None:
        task_name = task.get_task_name()

        try:
            if limiter is None:
                result = await task()
            else:
                async with acquire_limiter(limiter):
                    result = await task()

            results[task_name] = result
        except BaseException as exc:
            if execution_mode == ExecutionMode.FAIL_FAST:
                raise

            failures[task_name] = repr(exc)

    async with anyio.create_task_group() as task_group:
        for task in tasks:
            task_group.start_soon(
                runner,
                task,
                name=task.get_task_name(),
            )

    return ConcurrentResults(
        values=results,
        failures=failures,
    )


class ConcurrencyIntegrationMixin:
    def __init__(
        self,
        *,
        task_execution_mode: ExecutionMode = ExecutionMode.FAIL_FAST,
        task_limiter: CapacityLimiter | str | None = None,
        emit_warnings: bool = False,
    ) -> None:
        self.task_execution_mode = task_execution_mode
        self.task_limiter = task_limiter
        self.emit_warnings = emit_warnings

    async def map_operation[TInput, TResult](
        self,
        values: Iterable[TInput],
        operation: Callable[[TInput], Awaitable[TResult]],
        name_builder: Callable[[TInput], str] | None = None,
    ) -> ConcurrentResults[TResult]:
        result = await map_concurrently(
            values,
            operation=operation,
            name_builder=name_builder,
            execution_mode=self.task_execution_mode,
            limiter=self.task_limiter,
        )
        if self.emit_warnings and not result.succeeded:
            emit_internal_warning(result.stringify_warnings())

        return result

    async def dispatch[T](
        self,
        tasks: Iterable[DispatchableTask[T]],
    ) -> ConcurrentResults[T]:
        result = await dispatch_tasks(
            tasks,
            execution_mode=self.task_execution_mode,
            limiter=self.task_limiter,
        )
        if self.emit_warnings and not result.succeeded:
            emit_internal_warning(result.stringify_warnings())

        return result
