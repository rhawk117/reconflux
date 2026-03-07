import functools
from typing import Any, Self
from pydantic import BaseModel, ConfigDict, TypeAdapter
import dataclasses as dc

class ReconfluxModel(BaseModel):
    """
    Base pydantic model for reconflux
    """
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

class DataclassMixin:
    """Mixin providing dataclass utility methods as instance/class methods."""

    @classmethod
    def fields(cls) -> tuple[dc.Field[Any], ...]:
        """Calls Calls ``dataclasses.fields``"""
        return dc.fields(cls)  # type: ignore

    def asdict(self) -> dict[str, Any]:
        """Calls ``dataclasses.astuple``"""
        return dc.asdict(self)  # type: ignore

    def astuple(self) -> tuple[Any, ...]:
        """
        Calls ``dataclasses.astuple``
        """
        return dc.astuple(self)  # type: ignore

    def replace(self, **kwargs: Any) -> Self:
        """Calls ``dataclasses.replace``"""
        return dc.replace(self, **kwargs)  # type: ignore


@functools.lru_cache(maxsize=64)
def get_type_adapter[T: Any](type_: type[T]) -> TypeAdapter[T]:
    """
    Gets and caches a type adapter instance using
    ``functools.lru_cache`` with a max size of 64
    """
    return TypeAdapter(type_)

