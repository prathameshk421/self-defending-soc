"""CLI: python -m estate list|get|neighbors|resolve."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from estate.errors import EstateError
from estate.loader import load_inventory
from estate.query import Estate

DEFAULT_INVENTORY = (
    Path(__file__).resolve().parents[2] / "inventory" / "default.yaml"
)


def _default_inventory_path() -> Path:
    return DEFAULT_INVENTORY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="estate", description="Estate inventory CLI")
    parser.add_argument(
        "--inventory",
        type=Path,
        default=None,
        help="Path to inventory YAML (default: inventory/default.yaml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List assets (excludes retired by default)")

    get_p = sub.add_parser("get", help="Get asset by asset_id or by name")
    get_p.add_argument("id_or_name")
    get_p.add_argument("--lab-id", default="default")

    neigh_p = sub.add_parser("neighbors", help="List graph neighbors")
    neigh_p.add_argument("asset_id")
    neigh_p.add_argument("--depth", type=int, default=1)

    res_p = sub.add_parser("resolve", help="Resolve alias to asset_id")
    res_p.add_argument("alias")
    res_p.add_argument("--lab-id", default="default")

    return parser


def _asset_summary(asset) -> dict:
    return {
        "asset_id": asset.asset_id,
        "name": asset.name,
        "kind": asset.kind.value,
        "lab_id": asset.lab_id,
        "lifecycle": asset.lifecycle.value,
        "respond_allowed": asset.respond_allowed,
        "self_defense_class": asset.self_defense_class.value,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = args.inventory or _default_inventory_path()

    try:
        inventory = load_inventory(path)
        estate = Estate(inventory)

        if args.command == "list":
            for asset in estate.list(lab_id=inventory.lab_id):
                print(f"{asset.name}\t{asset.asset_id}\t{asset.kind.value}")
            return 0

        if args.command == "get":
            try:
                asset = estate.get(args.id_or_name)
            except EstateError:
                asset = estate.get_by_name(args.lab_id, args.id_or_name)
            print(json.dumps(_asset_summary(asset), indent=2))
            return 0

        if args.command == "neighbors":
            # Allow name or id
            try:
                asset_id = args.asset_id
                estate.get(asset_id)
            except EstateError:
                asset_id = estate.get_by_name(inventory.lab_id, args.asset_id).asset_id
            for asset in estate.neighbors(asset_id, depth=args.depth):
                print(f"{asset.name}\t{asset.asset_id}\t{asset.kind.value}")
            return 0

        if args.command == "resolve":
            asset_id = estate.resolve_alias(args.lab_id, args.alias)
            print(asset_id)
            return 0

        parser.error(f"unknown command: {args.command}")
        return 2
    except EstateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
