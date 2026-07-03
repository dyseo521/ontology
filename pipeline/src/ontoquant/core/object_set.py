"""ObjectSet — 오브젝트 집합.

- static: primary key 리스트로 저장 (데이터 변화와 무관하게 고정)
- dynamic: 필터 정의로 저장 (매 평가 시점의 매칭 결과)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ontoquant.core.store import OntologyStore


@dataclass
class ObjectSet:
    objectType: str
    kind: str = "dynamic"                      # static | dynamic
    pks: list[str] = field(default_factory=list)     # static
    where: Optional[dict] = None                     # dynamic

    def resolve(self, store: "OntologyStore") -> list[dict]:
        if self.kind == "static":
            out = []
            for pk in self.pks:
                obj = store.get(self.objectType, pk)
                if obj is not None:
                    out.append(obj)
            return out
        return store.query(self.objectType, where=self.where)

    def resolve_pks(self, store: "OntologyStore") -> list[str]:
        if self.kind == "static":
            return list(self.pks)
        pk_fields = {
            t: store.schema.objectTypes[t].primaryKey
            for t in store.schema.resolve_types(self.objectType)
        }
        out = []
        for obj in self.resolve(store):
            for t, f in pk_fields.items():
                if f in obj:
                    out.append(obj[f])
                    break
        return out

    def union(self, other: "ObjectSet", store: "OntologyStore") -> "ObjectSet":
        pks = list(dict.fromkeys(self.resolve_pks(store) + other.resolve_pks(store)))
        return ObjectSet(self.objectType, kind="static", pks=pks)

    def intersect(self, other: "ObjectSet", store: "OntologyStore") -> "ObjectSet":
        mine, theirs = self.resolve_pks(store), set(other.resolve_pks(store))
        return ObjectSet(self.objectType, kind="static", pks=[p for p in mine if p in theirs])

    def subtract(self, other: "ObjectSet", store: "OntologyStore") -> "ObjectSet":
        theirs = set(other.resolve_pks(store))
        return ObjectSet(self.objectType, kind="static",
                         pks=[p for p in self.resolve_pks(store) if p not in theirs])
