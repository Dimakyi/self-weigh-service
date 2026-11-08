import pytest

from app.kafka_producer import KafkaEventProducer


class FakeProducer:
    def __init__(self, config):
        self.config = config
        self.messages = []
        self.remaining = 0
        self.error = None

    def produce(self, topic, key, value, on_delivery):
        self.messages.append((topic, key, value))
        on_delivery(self.error, None)

    def flush(self, timeout):
        self.timeout = timeout
        return self.remaining


def test_kafka_producer_sends_and_waits_for_acknowledgement(monkeypatch):
    import app.kafka_producer as kafka_module

    fake = FakeProducer({})

    def fake_factory(config):
        fake.config = config
        return fake

    monkeypatch.setattr(kafka_module, "Producer", fake_factory)

    producer = KafkaEventProducer("localhost:9092", timeout_seconds=5)

    producer.send("selfweigh.events", "evt-1", '{"amount":100}')

    assert fake.messages == [
        ("selfweigh.events", "evt-1", '{"amount":100}')
    ]
    assert fake.timeout == 5
    assert fake.config == {
    "bootstrap.servers": "localhost:9092",
    "enable.idempotence": True,
    "acks": "all",
    "message.timeout.ms": 5000,
}


def test_kafka_producer_raises_when_delivery_fails(monkeypatch):
    import app.kafka_producer as kafka_module

    fake = FakeProducer({})
    fake.error = RuntimeError("broker unavailable")
    monkeypatch.setattr(kafka_module, "Producer", lambda config: fake)

    producer = KafkaEventProducer("localhost:9092")

    with pytest.raises(RuntimeError, match="Kafka delivery failed"):
        producer.send("selfweigh.events", "evt-1", "{}")


def test_kafka_producer_raises_when_flush_times_out(monkeypatch):
    import app.kafka_producer as kafka_module

    fake = FakeProducer({})
    fake.remaining = 1
    monkeypatch.setattr(kafka_module, "Producer", lambda config: fake)

    producer = KafkaEventProducer("localhost:9092")

    with pytest.raises(RuntimeError, match="delivery timed out"):
        producer.send("selfweigh.events", "evt-1", "{}")


@pytest.mark.parametrize(
    ("servers", "timeout"),
    [
        ("", 10),
        ("   ", 10),
        ("localhost:9092", 0),
        ("localhost:9092", -1),
        ("localhost:9092", float("nan")),
        ("localhost:9092", float("inf")),
    ],
)
def test_kafka_producer_rejects_invalid_configuration(servers, timeout):
    with pytest.raises(ValueError):
        KafkaEventProducer(servers, timeout)