from abc import ABC, abstractmethod
from typing import Optional


class ICacheRepository(ABC):

    @abstractmethod
    async def get(self, key: str) -> Optional[bytes]: ...

    @abstractmethod
    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...


    @abstractmethod
    async def add_to_list(self, key: str, value: bytes, ttl: Optional[int] = None) -> None: ...

    @abstractmethod
    async def get_list(self, key: str) -> list[bytes]: ...