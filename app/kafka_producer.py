"""Kafka delivery adapter for the transactional outbox."""
import math

from confluent_kafka import Producer


class KafkaEventProducer:
    """Send outbox events to Kafka and wait for broker acknowledgement."""

    def __init__(
        self,
        bootstrap_servers: str,
        timeout_seconds: float = 10.0,
    ):
        if not bootstrap_servers.strip():
            raise ValueError("Kafka bootstrap servers must not be blank")

        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Kafka timeout must be finite and above 0")

        self.timeout_seconds = timeout_seconds
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "enable.idempotence": True,
                "acks": "all",
                "message.timeout.ms": int(timeout_seconds * 1000),
            }
        )

    def send(self, topic: str, key: str, value: str) -> None:
        """Send one message and raise if Kafka does not acknowledge it."""
        errors = []

        self._producer.produce(
            topic,
            key=key,
            value=value,
            on_delivery=lambda error, message: errors.append(error)
            if error
            else None,
        )

        remaining = self._producer.flush(self.timeout_seconds)

        if remaining or errors:
            detail = errors[0] if errors else "delivery timed out"
            raise RuntimeError(f"Kafka delivery failed: {detail}")