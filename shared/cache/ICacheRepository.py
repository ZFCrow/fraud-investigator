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

    @abstractmethod
    async def increment(self, key: str, ttl: Optional[int] = None) -> int:
        """
        Add one to the counter at `key` (created at 1 if absent) and return the new count.

        `ttl` (seconds) is applied only when the key has no expiry yet, so it marks the end
        of a fixed window that later increments do not extend. Counting and setting the
        expiry must happen atomically: a counter left without one would never reset.
        """
        ...