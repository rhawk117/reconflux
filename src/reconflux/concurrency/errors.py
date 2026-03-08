




from typing import Self

from reconflux.core import ReconfluxError


class ConcurrencyError(ReconfluxError):
    error_code = 'concurrency_error'


class LimiterRegistryError(ConcurrencyError):

    @classmethod
    def total_tokens(cls, name: str, total_tokens: int) -> Self:
        return cls(
            'Limiter total_tokens must be at least 1.',
            context={
                'name': name,
                'total_tokens': total_tokens,
            },
        )

    @classmethod
    def already_registered(cls, name: str) -> Self:
        return cls(
            f'A limiter with the name `{name}` is already registered.',
            context={'name': name},
        )

    @classmethod
    def not_registered(cls, name: str) -> Self:
        return cls(
            f'Requested limiter `{name}` is not registered.',
            context={'name': name},
        )