from __future__ import annotations

import contextlib
import dataclasses as dc
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from anyio import CapacityLimiter

from reconflux.concurrency.errors import LimiterRegistryError
from reconflux.core import DataclassMixin

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable


class LimiterScope(StrEnum):
    GLOBAL = 'global'
    PROVIDER = 'provider'
    HOST = 'host'
    THREAD = 'thread'
    CUSTOM = 'custom'


@dc.dataclass(slots=True)
class CapacityLimitPolicy(DataclassMixin):
    name: str
    total_tokens: int
    scope: LimiterScope = LimiterScope.CUSTOM


@dc.dataclass(slots=True)
class LimiterRegistry:
    _named_limiters: dict[str, CapacityLimiter] = dc.field(default_factory=dict)
    _keyed_limiters: dict[str, dict[str, CapacityLimiter]] = dc.field(
        default_factory=dict
    )

    def register(
        self,
        name: str,
        *,
        total_tokens: int,
        overwrite: bool = False,
    ) -> CapacityLimiter:
        if total_tokens < 1:
            raise LimiterRegistryError.total_tokens(name, total_tokens)

        if not overwrite and name in self._named_limiters:
            raise LimiterRegistryError.already_registered(name)

        limiter = CapacityLimiter(total_tokens)
        self._named_limiters[name] = limiter
        return limiter

    def register_policy(
        self,
        policy: CapacityLimitPolicy,
        *,
        overwrite: bool = False,
    ) -> CapacityLimiter:
        return self.register(
            policy.name,
            total_tokens=policy.total_tokens,
            overwrite=overwrite,
        )

    def get(self, name: str) -> CapacityLimiter:
        try:
            return self._named_limiters[name]
        except KeyError as exc:
            raise LimiterRegistryError.not_registered(name) from exc

    def get_or_create(
        self,
        name: str,
        *,
        total_tokens: int,
    ) -> CapacityLimiter:
        existing_limiter = self._named_limiters.get(name)
        if existing_limiter is not None:
            return existing_limiter

        return self.register(name, total_tokens=total_tokens)

    def get_or_create_keyed(
        self,
        namespace: str,
        key: str,
        *,
        total_tokens: int,
    ) -> CapacityLimiter:
        namespace_limiters = self._keyed_limiters.setdefault(namespace, {})
        existing_limiter = namespace_limiters.get(key)

        if existing_limiter is not None:
            return existing_limiter

        limiter = CapacityLimiter(total_tokens)
        namespace_limiters[key] = limiter
        return limiter

    def snapshot(self) -> dict[str, float]:
        return {
            name: limiter.total_tokens for name, limiter in self._named_limiters.items()
        }


limiter_registry = LimiterRegistry()

@contextlib.asynccontextmanager
async def acquire_limiter(
    limiter: CapacityLimiter | str,
) -> AsyncGenerator[Any]:
    resolved_limiter = (
        limiter_registry.get(limiter) if isinstance(limiter, str) else limiter
    )

    async with resolved_limiter:
        yield resolved_limiter


async def run_limited[T](
    operation: Callable[..., Awaitable[T]],
    *operation_args: Any,
    limiter: CapacityLimiter | str,
    **operation_kwargs: Any,
) -> T:
    async with acquire_limiter(limiter):
        return await operation(*operation_args, **operation_kwargs)


def get_provider_limiter(
    provider_name: str,
    *,
    total_tokens: int,
) -> CapacityLimiter:
    return limiter_registry.get_or_create_keyed(
        'provider',
        provider_name,
        total_tokens=total_tokens,
    )


def get_host_limiter(
    host: str,
    *,
    total_tokens: int,
) -> CapacityLimiter:
    return limiter_registry.get_or_create_keyed(
        'host',
        host,
        total_tokens=total_tokens,
    )
