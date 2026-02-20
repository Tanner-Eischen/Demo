from __future__ import annotations

from redis import Redis
from rq import Queue
from backend.app.config import settings

def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url)

def get_queue() -> Queue:
    return Queue(settings.rq_queue, connection=get_redis())
