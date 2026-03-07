from typing import Any, ClassVar





class ReconfluxError(Exception):
    """
    The base class for all Reconflux Exceptions

    Class Variables
    ----------------
    default_message : str
        The default message for when the caller does not provide one
        default 'An unhandled runtime error from Reconflux occured'
    error_code : str
        A code assigned for the error, default 'reconflux_error'
    """
    default_message: ClassVar[str] = 'An unhandled runtime error from Reconflux occured'
    error_code: ClassVar[str] = 'reconflux_error'

    def __init__(
        self,
        message: str | None = None,
        *,
        context: dict[str, Any] | None
    ) -> None:
        self.message = message or self.default_message
        self.context = context or {}
        super().__init__(self.message)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def __str__(self) -> str:
        if not self.context:
            return self.message

        context_items = ', '.join(
            f'{key}={value!r}'
            for key, value in self.context.items()
        )
        return f'{self.name}: {self.message} [{context_items}]'
