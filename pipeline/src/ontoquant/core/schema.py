"""온톨로지 스키마 로더 — ontology/*.yaml 이 단일 진실 소스.

구성 요소:
  Object Type  = ObjectTypeDef  (apiName, primaryKey, titleProperty, properties, status ...)
  Interface    = InterfaceDef   (sharedProperties 를 구현 타입에 주입)
  Link Type    = LinkTypeDef    (cardinality, from/to 는 Object Type 또는 Interface)
  Action Type  = ActionTypeDef  (parameters + submissionCriteria + rules + sideEffects)
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

from ontoquant import config

PropertyType = Literal[
    "string", "integer", "double", "boolean", "date", "timestamp",
    "array", "struct", "json",
]


class PropertyDef(BaseModel):
    type: PropertyType
    description: Optional[str] = None
    nullable: bool = False
    enum: Optional[list[str]] = None
    owner: Optional[Literal["PIPELINE", "USER"]] = None
    fields: Optional[dict[str, "PropertyDef"]] = None   # struct
    items: Optional["PropertyDef"] = None               # array


class TimeSeriesPropertyDef(BaseModel):
    frequency: str = "daily"
    unit: str = "level"
    storage: Optional[str] = None
    derived: bool = False


class ObjectTypeDef(BaseModel):
    apiName: str
    displayName: str
    displayNamePlural: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    status: Literal["ACTIVE", "EXPERIMENTAL", "DEPRECATED"] = "EXPERIMENTAL"
    implements: list[str] = Field(default_factory=list)
    primaryKey: str
    titleProperty: str
    properties: dict[str, PropertyDef] = Field(default_factory=dict)
    timeSeriesProperties: dict[str, TimeSeriesPropertyDef] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_keys(self) -> "ObjectTypeDef":
        if self.primaryKey not in self.properties:
            raise ValueError(f"{self.apiName}: primaryKey '{self.primaryKey}' 가 properties에 없음")
        if self.titleProperty not in self.properties:
            raise ValueError(f"{self.apiName}: titleProperty '{self.titleProperty}' 가 properties에 없음")
        return self


class InterfaceDef(BaseModel):
    apiName: str
    displayName: str
    description: Optional[str] = None
    color: Optional[str] = None
    sharedProperties: dict[str, PropertyDef] = Field(default_factory=dict)
    implementedBy: list[str] = Field(default_factory=list)


class LinkTypeDef(BaseModel):
    apiName: str
    displayName: Optional[str] = None
    from_: str = Field(alias="from")
    to: str
    cardinality: Literal["ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY", "ONE_TO_ONE"]
    properties: dict[str, PropertyDef] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class ActionParameterDef(BaseModel):
    type: str  # string | double | integer | boolean | array | json | objectRef
    objectType: Optional[str] = None
    bind: Optional[str] = None
    required: bool = False
    default: Optional[Any] = None
    enum: Optional[list[str]] = None
    minLength: Optional[int] = None
    description: Optional[str] = None


class SubmissionCriterionDef(BaseModel):
    condition: str
    failureMessage: str


class ActionRuleDef(BaseModel):
    type: Literal["createObject", "modifyObject", "deleteObject", "createLink", "deleteLink", "functionRule"]
    objectType: Optional[str] = None
    target: Optional[str] = None
    values: Optional[dict[str, Any]] = None
    set: Optional[dict[str, Any]] = None
    linkType: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    toEach: Optional[str] = None
    function: Optional[str] = None
    when: Optional[str] = None
    description: Optional[str] = None

    model_config = {"populate_by_name": True}


class SideEffectDef(BaseModel):
    type: Literal["auditLog", "notification", "webhook"]
    channel: Optional[str] = None
    template: Optional[str] = None
    url: Optional[str] = None


class ActionTypeDef(BaseModel):
    apiName: str
    displayName: str
    description: Optional[str] = None
    parameters: dict[str, ActionParameterDef] = Field(default_factory=dict)
    submissionCriteria: list[SubmissionCriterionDef] = Field(default_factory=list)
    rules: list[ActionRuleDef] = Field(default_factory=list)
    sideEffects: list[SideEffectDef] = Field(default_factory=list)


class OntologySchema(BaseModel):
    objectTypes: dict[str, ObjectTypeDef]
    interfaces: dict[str, InterfaceDef]
    linkTypes: dict[str, LinkTypeDef]
    actionTypes: dict[str, ActionTypeDef]

    def resolve_types(self, name: str) -> list[str]:
        """Object Type 또는 Interface 이름 → 구체 Object Type 목록."""
        if name in self.objectTypes:
            return [name]
        if name in self.interfaces:
            return list(self.interfaces[name].implementedBy)
        raise KeyError(f"알 수 없는 타입: {name}")

    def implements(self, object_type: str, interface: str) -> bool:
        return object_type in self.interfaces.get(interface, InterfaceDef(apiName=interface, displayName=interface)).implementedBy


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schema(schema_dir: Path | None = None) -> OntologySchema:
    schema_dir = schema_dir or config.SCHEMA_DIR

    interfaces: dict[str, InterfaceDef] = {}
    for p in sorted((schema_dir / "interfaces").glob("*.yaml")):
        iface = InterfaceDef(**_load_yaml(p))
        interfaces[iface.apiName] = iface

    object_types: dict[str, ObjectTypeDef] = {}
    for p in sorted((schema_dir / "objects").glob("*.yaml")):
        raw = _load_yaml(p)
        # Interface sharedProperties 주입 (구현 타입은 공유 속성을 자동 보유)
        for iface_name in raw.get("implements", []):
            if iface_name not in interfaces:
                raise ValueError(f"{raw.get('apiName')}: 알 수 없는 인터페이스 {iface_name}")
            for prop_name, prop_def in interfaces[iface_name].sharedProperties.items():
                raw.setdefault("properties", {}).setdefault(
                    prop_name, prop_def.model_dump(exclude_none=True)
                )
        ot = ObjectTypeDef(**raw)
        object_types[ot.apiName] = ot

    # implementedBy 정합성 검증
    for iface in interfaces.values():
        for impl in iface.implementedBy:
            if impl not in object_types:
                raise ValueError(f"인터페이스 {iface.apiName}: 구현 타입 {impl} 없음")
            if iface.apiName not in object_types[impl].implements:
                raise ValueError(f"{impl} 은 {iface.apiName} 를 implements 로 선언해야 함")

    link_types: dict[str, LinkTypeDef] = {}
    links_raw = _load_yaml(schema_dir / "links" / "links.yaml")
    for entry in links_raw["linkTypes"]:
        lt = LinkTypeDef(**entry)
        for endpoint in (lt.from_, lt.to):
            if endpoint not in object_types and endpoint not in interfaces:
                raise ValueError(f"링크 {lt.apiName}: 알 수 없는 endpoint {endpoint}")
        link_types[lt.apiName] = lt

    action_types: dict[str, ActionTypeDef] = {}
    actions_dir = schema_dir / "actions"
    if actions_dir.is_dir():
        for p in sorted(actions_dir.glob("*.yaml")):
            at = ActionTypeDef(**_load_yaml(p))
            action_types[at.apiName] = at

    return OntologySchema(
        objectTypes=object_types,
        interfaces=interfaces,
        linkTypes=link_types,
        actionTypes=action_types,
    )


@lru_cache(maxsize=1)
def get_schema() -> OntologySchema:
    return load_schema()
