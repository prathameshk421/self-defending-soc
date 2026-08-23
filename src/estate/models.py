"""Pydantic models for the Layer 1 Estate inventory contract."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


SCHEMA_VERSION = 1


class AssetKind(str, Enum):
    LAB_SERVICE = "lab_service"
    LAB_ACCOUNT = "lab_account"
    LAB_NETWORK = "lab_network"
    LAB_FIREWALL_OBJECT = "lab_firewall_object"
    SOC_API = "soc_api"
    SOC_CONFIG = "soc_config"
    SOC_AGENT = "soc_agent"


class Owner(str, Enum):
    LAB_APP = "lab_app"
    SOC = "soc"


class Lifecycle(str, Enum):
    DECLARED = "declared"
    RUNNING = "running"
    STOPPED = "stopped"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class ExecutionRealm(str, Enum):
    LAB = "lab"


class SelfDefenseClass(str, Enum):
    WATCH_ONLY = "watch_only"
    CONTAIN_WITH_DEGRADED_MODE = "contain_with_degraded_mode"
    NEVER_ISOLATE = "never_isolate"


class Exposure(str, Enum):
    LOOPBACK = "loopback"
    LAB_NETWORK = "lab_network"
    PUBLISHED = "published"


class EdgeKind(str, Enum):
    DEPENDS_ON = "depends_on"
    SHARES_NETWORK = "shares_network"
    SHARES_VOLUME = "shares_volume"
    AUTHENTICATES_AS = "authenticates_as"
    CONFIGURES = "configures"
    EMITS_LOGS_AS = "emits_logs_as"


class LogSource(BaseModel):
    id: str
    kind: str
    locator: str


class AttackSurface(BaseModel):
    id: str
    locator: str
    scheme: str
    auth_scheme: str


class Handle(BaseModel):
    kind: str
    locator: str
    known_good_ref: Optional[str] = None


class CredentialRef(BaseModel):
    name: str
    ref: str


class RuntimeIdentity(BaseModel):
    compose_project: Optional[str] = None
    compose_service: Optional[str] = None
    replica_index: Optional[int] = None
    container_id: Optional[str] = None
    ip: Optional[str] = None
    image_digest: Optional[str] = None
    observed_at: Optional[str] = None
    stale: bool = True


class Asset(BaseModel):
    asset_id: str
    lab_id: str
    kind: AssetKind
    name: str
    owner: Owner
    lifecycle: Lifecycle = Lifecycle.DECLARED
    execution_realm: ExecutionRealm = ExecutionRealm.LAB
    respond_allowed: bool = False
    self_defense_class: SelfDefenseClass = SelfDefenseClass.WATCH_ONLY
    owner_ref: str = ""
    approval_policy_id: str = ""
    exposure: Exposure = Exposure.LAB_NETWORK
    aliases: list[str] = Field(default_factory=list)
    log_sources: list[LogSource] = Field(default_factory=list)
    attack_surface: list[AttackSurface] = Field(default_factory=list)
    containment_handles: list[Handle] = Field(default_factory=list)
    restore_handles: list[Handle] = Field(default_factory=list)
    credential_refs: list[CredentialRef] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    in_scope_red_team: bool = False
    red_team_skip: bool = False
    runtime_identity: Optional[RuntimeIdentity] = None


class Edge(BaseModel):
    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    kind: EdgeKind

    model_config = {"populate_by_name": True}


class Inventory(BaseModel):
    schema_version: int
    lab_id: str
    assets: list[Asset]
    edges: list[Edge] = Field(default_factory=list)
