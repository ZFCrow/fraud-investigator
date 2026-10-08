from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request

from server.core.dependencies import get_redis_client
from shared.settings import settings


async def _hit(redis: aioredis.Redis, key: str, window_s: int, limit: int, message: str) -> None:
    """Count one request against `key`; 429 once the window's limit is passed. limit <= 0 is off."""
    if limit <= 0:
        return
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_s)
    if count > limit:
        raise HTTPException(status_code=429, detail=message)


async def enforce_rate_limit(
        request: Request,
        redis: aioredis.Redis = Depends(get_redis_client),
) -> None:
    """
    Keeps a public demo from draining the model credits: every question is several
    LLM calls. Both limits are off (0) unless set in the environment.

    The visitor is identified by X-Client-Id, which the chat UI sets to the browser's
    IP -- the UI calls this API from inside the container, so request.client is
    always localhost there.
    """
    client = request.headers.get("x-client-id") or (request.client.host if request.client else "unknown")
    await _hit(redis, f"ratelimit:minute:{client}", 60, settings.RATE_LIMIT_PER_MINUTE,
               "You're asking faster than this demo allows. Please wait a minute and try again.")

    today = datetime.now(timezone.utc).date().isoformat()
    await _hit(redis, f"ratelimit:day:{today}", 86400, settings.RATE_LIMIT_PER_DAY,
               "This demo has reached its question limit for today. Please come back tomorrow.")
