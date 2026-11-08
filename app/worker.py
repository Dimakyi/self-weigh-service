"""Outbox worker: repeatedly publishes pending events until stopped."""

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
    """Log an event instead of sending it to an external broker."""
    logger.info(
        "event %s %s %s",
        event_id,
        event_type,
        json.dumps(payload, sort_keys=True),
    )


def make_kafka_delivery(producer) -> DeliveryFunction:
    """Adapt the Kafka producer to the outbox delivery interface."""

    def deliver(event_id: str, event_type: str, payload: dict) -> None:
        message = json.dumps(
            {
                "event_id": event_id,
                "event_type": event_type,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        producer.send(
            config.KAFKA_TOPIC,
            event_id,
            message,
        )

    return deliver


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
    """Publish pending events until told to stop."""
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

    if config.KAFKA_BOOTSTRAP_SERVERS:
        from app.kafka_producer import KafkaEventProducer

        producer = KafkaEventProducer(
            config.KAFKA_BOOTSTRAP_SERVERS,
            timeout_seconds=config.KAFKA_DELIVERY_TIMEOUT_SECONDS,
        )
        deliver = make_kafka_delivery(producer)
        logger.info("Kafka delivery enabled: topic=%s", config.KAFKA_TOPIC)
    else:
        deliver = log_delivery
        logger.info("Kafka not configured; using logging delivery")

    run_forever(deliver, stop=stop)


if __name__ == "__main__":
    main()