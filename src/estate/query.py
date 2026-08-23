"""Estate query API — get, list, neighbors, resolve_alias, assert_respond_target."""

from __future__ import annotations

from collections import deque
from typing import Optional

from estate.errors import AmbiguousAlias, NotFound, RespondForbidden
from estate.models import Asset, EdgeKind, Inventory, Lifecycle, SelfDefenseClass


class Estate:
    def __init__(self, inventory: Inventory) -> None:
        self._inventory = inventory
        self._by_id: dict[str, Asset] = {a.asset_id: a for a in inventory.assets}
        self._alias_index: dict[tuple[str, str], list[str]] = {}
        for asset in inventory.assets:
            for alias in asset.aliases:
                key = (asset.lab_id, alias)
                self._alias_index.setdefault(key, []).append(asset.asset_id)

    @property
    def inventory(self) -> Inventory:
        return self._inventory

    def get(self, asset_id: str) -> Asset:
        try:
            return self._by_id[asset_id]
        except KeyError as exc:
            raise NotFound(f"asset_id not found: {asset_id}") from exc

    def get_by_name(self, lab_id: str, name: str) -> Asset:
        for asset in self._inventory.assets:
            if asset.lab_id == lab_id and asset.name == name:
                return asset
        raise NotFound(f"asset not found: lab_id={lab_id!r} name={name!r}")

    def list(
        self,
        *,
        lab_id: Optional[str] = None,
        kind: Optional[str] = None,
        respond_allowed: Optional[bool] = None,
        in_scope_red_team: Optional[bool] = None,
        lifecycle: Optional[str] = None,
        include_retired: bool = False,
    ) -> list[Asset]:
        results: list[Asset] = []
        for asset in self._inventory.assets:
            if not include_retired and asset.lifecycle == Lifecycle.RETIRED:
                if lifecycle != Lifecycle.RETIRED.value:
                    continue
            if lab_id is not None and asset.lab_id != lab_id:
                continue
            if kind is not None and asset.kind.value != kind:
                continue
            if respond_allowed is not None and asset.respond_allowed != respond_allowed:
                continue
            if (
                in_scope_red_team is not None
                and asset.in_scope_red_team != in_scope_red_team
            ):
                continue
            if lifecycle is not None and asset.lifecycle.value != lifecycle:
                continue
            results.append(asset)
        return results

    def neighbors(
        self,
        asset_id: str,
        *,
        kinds: Optional[list[EdgeKind | str]] = None,
        depth: int = 1,
    ) -> list[Asset]:
        if asset_id not in self._by_id:
            raise NotFound(f"asset_id not found: {asset_id}")
        if depth < 1:
            return []

        kind_filter: set[str] | None = None
        if kinds is not None:
            kind_filter = {
                k.value if isinstance(k, EdgeKind) else str(k) for k in kinds
            }

        seen: set[str] = {asset_id}
        found: list[Asset] = []
        queue: deque[tuple[str, int]] = deque([(asset_id, 0)])

        while queue:
            current, d = queue.popleft()
            if d >= depth:
                continue
            for edge in self._inventory.edges:
                if kind_filter is not None and edge.kind.value not in kind_filter:
                    continue
                nxt: str | None = None
                if edge.from_id == current:
                    nxt = edge.to_id
                elif edge.to_id == current:
                    nxt = edge.from_id
                if nxt is None or nxt in seen:
                    continue
                seen.add(nxt)
                neighbor = self._by_id[nxt]
                found.append(neighbor)
                queue.append((nxt, d + 1))
        return found

    def resolve_alias(self, lab_id: str, alias: str) -> str:
        matches = self._alias_index.get((lab_id, alias), [])
        if not matches:
            raise NotFound(f"alias not found: lab_id={lab_id!r} alias={alias!r}")
        if len(matches) > 1:
            raise AmbiguousAlias(
                f"ambiguous alias: lab_id={lab_id!r} alias={alias!r} -> {matches}"
            )
        return matches[0]

    def assert_respond_target(self, asset_id: str) -> None:
        """Fail closed if this asset must not be isolated / contained."""
        asset = self.get(asset_id)

        if not asset.respond_allowed:
            raise RespondForbidden(
                f"respond_allowed=false for asset {asset.name!r} ({asset_id})"
            )
        if asset.execution_realm.value != "lab":
            raise RespondForbidden(
                f"execution_realm={asset.execution_realm.value!r} is not lab"
            )
        if asset.self_defense_class == SelfDefenseClass.NEVER_ISOLATE:
            raise RespondForbidden(
                f"self_defense_class=never_isolate for asset {asset.name!r}"
            )
        if "isolate" in asset.forbidden_actions:
            raise RespondForbidden(
                f"isolate is in forbidden_actions for asset {asset.name!r}"
            )

        # Declared with no containment handle that works offline → cannot isolate.
        if asset.lifecycle == Lifecycle.DECLARED and not asset.containment_handles:
            raise RespondForbidden(
                f"lifecycle=declared and no containment_handles for {asset.name!r}"
            )

        # Config-style assets: restore only — no isolate if no containment handles.
        if not asset.containment_handles:
            raise RespondForbidden(
                f"no containment_handles for asset {asset.name!r}"
            )
