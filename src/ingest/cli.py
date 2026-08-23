"""CLI: python -m ingest run|check|emit|schema."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from estate.errors import EstateError
from estate.loader import load_inventory
from estate.query import Estate

from ingest.config import load_config
from ingest.errors import IngestError
from ingest.models import TOPIC_RAW, RawRecord
from ingest.pipeline import Pipeline
from ingest.schema_gen import SCHEMA_MODELS, generate_schema_text
from ingest.schema_sync import sync_schemas

DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest", description="Ingest pipeline CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Run the normalizer pipeline (requires [kafka] extra)")
    sub.add_parser("check", help="Validate config, inventory, and registry schemas")

    emit_p = sub.add_parser("emit", help="Produce one test raw record")
    emit_p.add_argument("--source-alias", default="lab-shop")
    emit_p.add_argument("--raw", default="ingest emit test record")

    schema_p = sub.add_parser("schema", help="Schema operations")
    schema_sub = schema_p.add_subparsers(dest="schema_command", required=True)
    export_p = schema_sub.add_parser(
        "export", help="Regenerate JSON schema files from the Pydantic models"
    )
    export_p.add_argument("--out", type=Path, default=DEFAULT_SCHEMA_DIR)

    return parser


def _cmd_schema_export(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMA_MODELS.items():
        (out_dir / filename).write_text(generate_schema_text(model), encoding="utf-8")
        print(f"wrote {out_dir / filename}")
    return 0


def _resolver(config):
    inventory = load_inventory(config.inventory_path)
    return Estate(inventory)


def _cmd_check() -> int:
    config = load_config()
    _resolver(config)
    sync_schemas(config.registry_url)
    print("ok: config valid, inventory loads, registry schemas in sync")
    return 0


def _cmd_run() -> int:
    config = load_config()
    resolver = _resolver(config)
    sync_schemas(config.registry_url)

    from ingest.kafka_adapter import KafkaConsumerAdapter, KafkaProducerAdapter

    pipeline = Pipeline(
        KafkaConsumerAdapter(config),
        KafkaProducerAdapter(config),
        resolver,
        max_payload_bytes=config.max_payload_bytes,
    )
    pipeline.run_forever()
    return 0


def _cmd_emit(source_alias: str, raw: str) -> int:
    config = load_config()

    from ingest.kafka_adapter import KafkaProducerAdapter

    record = RawRecord(
        lab_id=config.lab_id,
        source_alias=source_alias,
        source_type="webhook",
        collector="ingest-cli",
        raw=raw,
        observed_at=datetime.now(timezone.utc),
    )
    producer = KafkaProducerAdapter(config)
    producer.produce(
        TOPIC_RAW, key=source_alias, value=record.model_dump_json().encode("utf-8")
    )
    failures = producer.flush()
    if failures:
        print(f"error: delivery failed: {failures[0].error}", file=sys.stderr)
        return 1
    print(f"emitted 1 raw record for {source_alias!r} to {TOPIC_RAW}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "schema":
            return _cmd_schema_export(args.out)
        if args.command == "check":
            return _cmd_check()
        if args.command == "run":
            return _cmd_run()
        if args.command == "emit":
            return _cmd_emit(args.source_alias, args.raw)
        parser.error(f"unknown command: {args.command}")
        return 2
    except (IngestError, EstateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
