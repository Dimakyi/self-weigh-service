"""Outbox worker: repeatedly runs the publisher until told to stop.

Run with ``python -m app.worker``. Until a Kafka producer is added, events are
delivered to ``log_delivery``, which writes each one to the log.
"""
import json
import logging
import os
import signal
import socket
import threading

from app import config
from app.outbox_publisher import DeliveryFunction, publish_pending

logger = logging.getLogger("selfweigh.worker")


def log_delivery(event_id: str, event_type: str, payload: dict) -> None:
    """Stand-in delivery function: log the event instead of sending it."""
    logger.info(
        "event %s %s %s",
        event_id,
        event_type,
        json.dumps(payload, sort_keys=True),
    )


def default_worker_id() -> str:
    return f"worker-{socket.gethostname()}-{os.getpid()}"[:100]


def run_forever(
    deliver: DeliveryFunction,
    *,
    stop: threading.Event,
    poll_seconds: float = config.WORKER_POLL_SECONDS,
    batch_size: int = config.WORKER_BATCH_SIZE,
    lease_seconds: int = config.WORKER_LEASE_SECONDS,
    worker_id: str | None = None,
) -> None:
    """Publish pending events until ``stop`` is set.

    A failed batch (for example the database is down, or the tables do not
    exist yet) is logged and retried after ``poll_seconds``; it never ends the
    loop. When nothing was published the worker waits ``poll_seconds`` before
    polling again, and the wait ends immediately if ``stop`` is set.
    """
    worker_id = worker_id or default_worker_id()
    logger.info("worker %s started", worker_id)

    while not stop.is_set():
        try:
            published = publish_pending(
                deliver,
                limit=batch_size,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
        except Exception:
            logger.exception("publish batch failed; will retry")
            published = 0

        if published == 0:
            stop.wait(poll_seconds)

    logger.info("worker %s stopped", worker_id)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stop = threading.Event()

    def request_stop(signum, frame):
        logger.info("received signal %s; finishing current batch", signum)
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    run_forever(log_delivery, stop=stop)


if __name__ == "__main__":
    main()
