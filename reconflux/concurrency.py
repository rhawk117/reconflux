from __future__ import annotations

import contextlib
import dataclasses as dc
from typing import TYPE_CHECKING, Any, NamedTuple, ParamSpec, Self, TypeVar

import anyio

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from anyio.abc import TaskGroup

Parameters = ParamSpec('Parameters')
InputType = TypeVar('InputType')
ResultType = TypeVar('ResultType')


def resolve_deadline(
    timeout: float | None = None,
    deadline: float | None = None,
) -> float | None:
    """Resolve the effective planner deadline.

    Parameters
    ----------
    timeout : float | None, default=None
        Relative timeout in seconds.
    deadline : float | None, default=None
        Absolute AnyIO deadline.

    Returns
    -------
    float | None
        The absolute deadline value to use with ``anyio.CancelScope``, or
        ``None`` when no deadline should be applied.

    Raises
    ------
    ValueError
        If both ``timeout`` and ``deadline`` are provided.
    """
    if timeout is not None and deadline is not None:
        raise ValueError('Only one of timeout or deadline may be provided.')

    if deadline is not None:
        return deadline

    if timeout is not None:
        return anyio.current_time() + timeout

    return None


class TaskExecutorResult[T](NamedTuple):
    """Result container for task execution.

    Parameters
    ----------
    results : dict[str, T]
        Mapping of task names to successful task results.
    errors : dict[str, str]
        Mapping of task names to stringified errors.
    """

    results: dict[str, T]
    errors: dict[str, str]

    @property
    def okay(self) -> bool:
        """Return whether all tasks completed successfully.

        Returns
        -------
        bool
            ``True`` when no task errors were recorded, otherwise ``False``.
        """
        return not self.errors


class TaskPlanner(NamedTuple):
    """Simple concurrency planner for grouped AnyIO task execution.

    Parameters
    ----------
    fail_fast : bool, default=True
        Whether the first task error should be re-raised and allow the task
        group to cancel sibling tasks.
    deadline : float | None, default=None
        Absolute AnyIO deadline applied to the task group's cancel scope.
    limiter : anyio.CapacityLimiter | None, default=None
        Optional concurrency limiter shared by all scheduled tasks.
    """

    fail_fast: bool = True
    deadline: float | None = None
    limiter: anyio.CapacityLimiter | None = None

    @classmethod
    def create(
        cls,
        *,
        concurrency_limit: int | None = None,
        timeout: float | None = None,
        deadline: float | None = None,
        fail_fast: bool = True,
    ) -> Self:
        """Create a planner from high-level concurrency inputs.

        Parameters
        ----------
        concurrency_limit : int | None, default=None
            Maximum number of concurrently running tasks. If ``None``, no
            explicit limiter is used.
        timeout : float | None, default=None
            Relative timeout in seconds.
        deadline : float | None, default=None
            Absolute AnyIO deadline.
        fail_fast : bool, default=True
            Whether the first task error should abort the group.

        Returns
        -------
        Self
            A configured task planner instance.

        Raises
        ------
        ValueError
            If ``concurrency_limit`` is not positive.
        ValueError
            If both ``timeout`` and ``deadline`` are provided.
        """
        if concurrency_limit is not None and concurrency_limit <= 0:
            raise ValueError('concurrency_limit must be greater than 0.')

        limiter = (
            anyio.CapacityLimiter(concurrency_limit)
            if concurrency_limit is not None
            else None
        )
        actual_deadline = resolve_deadline(timeout=timeout, deadline=deadline)

        return cls(
            fail_fast=fail_fast,
            deadline=actual_deadline,
            limiter=limiter,
        )

    @contextlib.asynccontextmanager
    async def group(self) -> AsyncGenerator[TaskGroup]:
        """Create a task group configured with the planner deadline.

        Yields
        ------
        TaskGroup
            The configured AnyIO task group.
        """
        async with anyio.create_task_group() as task_group:
            if self.deadline is not None:
                task_group.cancel_scope.deadline = self.deadline

            yield task_group


@dc.dataclass(slots=True)
class TaskExecutor[InputType, ResultType]:
    """Execute a named set of tasks through a shared planner.

    Parameters
    ----------
    planner : TaskPlanner
        Planner controlling timeout, cancellation, and concurrency limits.
    schedule : dict[str, InputType]
        Mapping of task names to input payloads.
    runner : Callable[[InputType], Awaitable[ResultType]]
        Async callable used to process each payload.
    """

    schedule: dict[str, InputType]
    runner: Callable[[InputType], Awaitable[ResultType]]
    planner: TaskPlanner = dc.field(default_factory=TaskPlanner)
    _successes: dict[str, ResultType] = dc.field(default_factory=dict, init=False)
    _errors: dict[str, str] = dc.field(default_factory=dict, init=False)

    async def _execute_one(self, name: str, payload: InputType) -> None:
        """Execute a single scheduled task.

        Parameters
        ----------
        name : str
            Task name.
        payload : InputType
            Task input payload.

        Raises
        ------
        Exception
            Re-raises the original exception when ``fail_fast`` is enabled.
        """
        try:
            if self.planner.limiter is None:
                result = await self.runner(payload)
            else:
                async with self.planner.limiter:
                    result = await self.runner(payload)

            self._successes[name] = result
        except Exception as exc:
            self._errors[name] = repr(exc)

            if self.planner.fail_fast:
                raise

    async def run(self) -> TaskExecutorResult[ResultType]:
        """Run all scheduled tasks.

        Returns
        -------
        TaskExecutorResult[ResultType]
            Aggregated successes and errors.

        Raises
        ------
        Exception
            Propagates the first task error when ``planner.fail_fast`` is
            enabled, allowing AnyIO's task group to cancel remaining siblings.
        """
        self._successes.clear()
        self._errors.clear()

        async with self.planner.group() as task_group:
            for task_name, payload in self.schedule.items():
                task_group.start_soon(
                    self._execute_one,
                    task_name,
                    payload,
                    name=task_name,
                )

        return TaskExecutorResult(
            results=dict(self._successes),
            errors=dict(self._errors),
        )

@contextlib.contextmanager
def shielded_cancel_scope() -> Any:
    with anyio.CancelScope(shield=True) as cancel_scope:
        yield cancel_scope


def current_effective_deadline() -> float:
    return anyio.current_effective_deadline()



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


async def run_concurrently[InputType, ResultType](
    schedule: dict[str, InputType],
    runner: Callable[[InputType], Awaitable[ResultType]],
    *,
    concurrency_limit: int | None = None,
    timeout: float | None = None,  # noqa: ASYNC109
    deadline: float | None = None,
    fail_fast: bool = True,
) -> TaskExecutorResult[ResultType]:

    planner = TaskPlanner.create(
        concurrency_limit=concurrency_limit,
        timeout=timeout,
        deadline=deadline,
        fail_fast=fail_fast,
    )
    executor = TaskExecutor(
        planner=planner,
        schedule=schedule,
        runner=runner,
    )

    return await executor.run()
