from __future__ import annotations

from redis import Redis
from rq import Worker, Queue

from backend.app.config import settings

def main() -> None:
    redis = Redis.from_url(settings.redis_url)
    qname = settings.rq_queue
    queue = Queue(qname, connection=redis)
    worker = Worker([queue], connection=redis)
    worker.work(with_scheduler=False)

if __name__ == "__main__":
    main()
