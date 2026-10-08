from typing import Optional

import redis.asyncio as aioredis

from shared.cache.ICacheRepository import ICacheRepository


class RedisCacheRepository(ICacheRepository):
    def __init__(self, client: aioredis.Redis):
        self._client = client

    async def get(self, key: str) -> Optional[bytes]:
        return await self._client.get(key)

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        if ttl is not None:
            await self._client.setex(key, ttl, value)
        else:
            await self._client.set(key, value)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        return bool(await self._client.exists(key))

    async def close(self) -> None:
        await self._client.aclose()

    async def add_to_list(self, key: str, value: bytes, ttl: Optional[int] = None) -> None: 
        await self._client.rpush(key, value)
        if ttl is not None:
            await self._client.expire(key, ttl)
    
    async def get_list(self, key: str) -> list[bytes]:
        values = await self._client.lrange(key, 0, -1)
        return values

    async def increment(self, key: str, ttl: Optional[int] = None) -> int:
        # one MULTI/EXEC transaction: the count and its expiry are set together
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            if ttl is not None:
                pipe.expire(key, ttl, nx=True)  # NX: only if the key has no expiry yet
            results = await pipe.execute()
        return results[0]
    
