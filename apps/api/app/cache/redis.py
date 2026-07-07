from functools import lru_cache

from redis import Redis

from app.config import get_settings


@lru_cache
def get_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def ping_redis() -> bool:
    return bool(get_redis_client().ping())
