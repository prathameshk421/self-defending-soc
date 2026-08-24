import json

from estate.errors import NotFound

from ingest.models import TOPIC_DLQ, TOPIC_EVENTS, TOPIC_UNMAPPED
from ingest.pipeline import Pipeline
from ingest.ports import DeliveryFailure
from tests.ingest.conftest import (
    FakeConsumer,
    FakeProducer,
    make_raw_message,
    make_raw_record,
)

MAX_BYTES = 262144


def _pipeline(messages, resolver, producer=None):
    producer = producer or FakeProducer()
    consumer = FakeConsumer(messages)
    return (
        Pipeline(consumer, producer, resolver, max_payload_bytes=MAX_BYTES),
        consumer,
        producer,
    )


def test_happy_path_event_produced_and_committed(resolver):
    message = make_raw_message(make_raw_record())
    pipeline, consumer, producer = _pipeline([message], resolver)

    result = pipeline.run_once()

    assert result.events == 1 and result.committed
    assert len(producer.produced) == 1
    request = producer.produced[0]
    assert request.topic == TOPIC_EVENTS
    assert request.key == "asset-shop"  # keyed by asset_id for per-asset ordering
    assert request.headers["schema_version"] == "1"
    body = json.loads(request.value)
    assert body["asset_id"] == "asset-shop"
    assert consumer.committed == [message]


def test_unknown_alias_routed_to_unmapped(resolver):
    message = make_raw_message(make_raw_record(source_alias="ghost-service"))
    pipeline, consumer, producer = _pipeline([message], resolver)

    result = pipeline.run_once()

    assert result.unmapped == 1 and result.committed
    request = producer.produced[0]
    assert request.topic == TOPIC_UNMAPPED
    assert request.headers["reason"] == "alias not found"
    # original envelope carried intact for later reprocessing
    assert json.loads(request.value)["source_alias"] == "ghost-service"


def test_garbage_routed_to_dlq_and_committed(resolver):
    message = make_raw_message(make_raw_record())
    garbage = type(message)(
        topic=message.topic, partition=0, offset=1, key=None, value=b"not json"
    )
    pipeline, consumer, producer = _pipeline([garbage], resolver)

    result = pipeline.run_once()

    assert result.dlq == 1 and result.committed
    assert producer.produced[0].topic == TOPIC_DLQ


def test_delivery_failure_blocks_commit(resolver):
    message = make_raw_message(make_raw_record())
    producer = FakeProducer()
    producer.fail_next_flush = [
        DeliveryFailure(topic=TOPIC_EVENTS, key="asset-shop", error="broker down")
    ]
    pipeline, consumer, producer = _pipeline([message], resolver, producer)

    result = pipeline.run_once()

    assert not result.committed
    assert result.failures == 1
    assert consumer.committed == []


def test_resolver_blowup_goes_to_dlq_not_crash():
    class ExplodingResolver:
        def resolve_alias(self, lab_id, alias):
            raise RuntimeError("boom")

    message = make_raw_message(make_raw_record())
    pipeline, consumer, producer = _pipeline([message], ExplodingResolver())

    result = pipeline.run_once()

    assert result.dlq == 1 and result.committed
    assert producer.produced[0].topic == TOPIC_DLQ
    assert "boom" in producer.produced[0].headers["reason"]


def test_empty_poll_commits_nothing(resolver):
    pipeline, consumer, producer = _pipeline([], resolver)

    result = pipeline.run_once()

    assert result.consumed == 0 and not result.committed
    assert producer.flush_calls == 0


def test_batch_commits_all_partitions(resolver):
    m0 = make_raw_message(make_raw_record(), offset=4, partition=0)
    m1 = make_raw_message(
        make_raw_record(source_alias="lab-idp"), offset=9, partition=1
    )
    pipeline, consumer, producer = _pipeline([m0, m1], resolver)

    result = pipeline.run_once()

    assert result.events == 2 and result.committed
    assert consumer.committed == [m0, m1]
