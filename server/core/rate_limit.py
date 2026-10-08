from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request

from server.core.dependencies import get_cache_repo
from shared.cache.ICacheRepository import ICacheRepository
from shared.settings import settings


async def _hit(cache_repo: ICacheRepository, key: str, window_s: int, limit: int, 
               message: str) -> None:
    """Count one request against `key`; 429 once the window's limit is passed. limit <= 0 is off."""
    if limit <= 0:
        return
    count : int = await cache_repo.increment(key, 
                                             ttl=window_s)
    if count > limit:
        raise HTTPException(status_code=429, detail=message)


async def enforce_rate_limit(
        request: Request,
        cache_repo: ICacheRepository = Depends(get_cache_repo),
) -> None:
    """
    Keeps a public demo from draining the model credits: every question is several
    LLM calls. Both limits are off (0) unless set in the environment.

    The visitor is identified by X-Client-Id, which the chat UI sets to the browser's
    IP -- the UI calls this API from inside the container, so request.client is
    always localhost there.
    """
    client = request.headers.get("x-client-id") or (request.client.host if request.client else "unknown")
    await _hit(
        cache_repo = cache_repo, 
        key = f"ratelimit:minute:{client}", 
        window_s = 60, 
        limit = settings.RATE_LIMIT_PER_MINUTE,
        message = "You're asking faster than this demo allows. Please wait a minute and try again."
    )

    today = datetime.now(timezone.utc).date().isoformat()
    await _hit(
        cache_repo = cache_repo, 
        key = f"ratelimit:day:{today}", 
        window_s = 86400, 
        limit = settings.RATE_LIMIT_PER_DAY,
        message = "This demo has reached its question limit for today. Please come back tomorrow."
    )
