"""OntologyStore — 온톨로지 런타임.

- 정본: 계층별 JSONL/JSON 파일 (git 커밋 대상)
    data/source/objects/{Type}.jsonl      파이프라인 ingest 산출 (스냅샷)
    data/computed/objects/{Type}.jsonl    파이프라인 compute 산출 (스냅샷)
    data/writeback/objects/{Type}.jsonl   액션 편집 (append-only, last-wins, tombstone 지원)
    data/{layer}/links/{linkType}.jsonl   링크 (동일 규칙)
    data/writeback/portfolio.json         포트폴리오 정본 (어댑터로 오브젝트화)
- 런타임: 전량 메모리 로드 + 양방향 인접 인덱스 (이 규모에서 <1초 재구축)
- 계층 병합: source → computed → writeback (→ overlay) 순, 속성 단위 last-wins
- 속성 소유권: owner=USER 는 writeback/overlay 만, owner=PIPELINE 은 source/computed/overlay 만 쓸 수 있다
- overlay: 시나리오 샌드박스 (fork) — 소유권 검사 없이 최우선 병합
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from ontoquant import config
from ontoquant.core.schema import OntologySchema, get_schema

LAYERS = ("source", "computed", "writeback")
TOMBSTONE = "__deleted__"


@dataclass
class LinkRecord:
    linkType: str
    fromType: str
    fromPk: str
    toType: str
    toPk: str
    props: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "fromType": self.fromType, "from": self.fromPk,
            "toType": self.toType, "to": self.toPk,
            **({"props": self.props} if self.props else {}),
        }


@dataclass
class Neighbor:
    objectType: str
    pk: str
    obj: dict
    link: LinkRecord


def _read_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


class OntologyStore:
    def __init__(
        self,
        data_dir: Path | None = None,
        overlay_dir: Path | None = None,
        schema: OntologySchema | None = None,
    ):
        self.data_dir = data_dir or config.DATA_DIR
        self.overlay_dir = overlay_dir
        self.schema = schema or get_schema()
        # layer -> type -> pk -> props
        self._layer_objects: dict[str, dict[str, dict[str, dict]]] = {}
        # merged: type -> pk -> props
        self._objects: dict[str, dict[str, dict]] = defaultdict(dict)
        self._links: dict[str, list[LinkRecord]] = defaultdict(list)
        self._out_idx: dict[tuple[str, str], dict[str, list[LinkRecord]]] = defaultdict(lambda: defaultdict(list))
        self._in_idx: dict[tuple[str, str], dict[str, list[LinkRecord]]] = defaultdict(lambda: defaultdict(list))

    # ---------------------------------------------------------------- build

    def build(self) -> "OntologyStore":
        self._layer_objects = {layer: defaultdict(dict) for layer in LAYERS}
        if self.overlay_dir:
            self._layer_objects["overlay"] = defaultdict(dict)
        self._objects = defaultdict(dict)
        self._links = defaultdict(list)
        self._out_idx = defaultdict(lambda: defaultdict(list))
        self._in_idx = defaultdict(lambda: defaultdict(list))

        for layer in self._iter_layers():
            base = self._layer_dir(layer)
            obj_dir = base / "objects"
            if obj_dir.is_dir():
                for path in sorted(obj_dir.glob("*.jsonl")):
                    object_type = path.stem
                    if object_type not in self.schema.objectTypes:
                        continue
                    store = self._layer_objects[layer][object_type]
                    pk_field = self.schema.objectTypes[object_type].primaryKey
                    for row in _read_jsonl(path):
                        pk = row.get(pk_field)
                        if pk is None:
                            continue
                        if row.get(TOMBSTONE):
                            store.pop(pk, None)
                        else:
                            store[pk] = {k: v for k, v in row.items() if k != TOMBSTONE}

        # portfolio.json 어댑터 (writeback 계층)
        self._load_portfolio_writeback()

        # 병합 (속성 단위 last-wins)
        deleted: set[tuple[str, str]] = set()
        for layer in self._iter_layers():
            for object_type, objs in self._layer_objects[layer].items():
                for pk, props in objs.items():
                    merged = self._objects[object_type].get(pk, {})
                    merged.update(props)
                    self._objects[object_type][pk] = merged

        # 링크 로드 (뒤 계층이 전체를 대체하지 않고 합집합; 동일 (from,to) 는 뒤가 우선)
        seen: dict[tuple, LinkRecord] = {}
        for layer in self._iter_layers():
            link_dir = self._layer_dir(layer) / "links"
            if not link_dir.is_dir():
                continue
            for path in sorted(link_dir.glob("*.jsonl")):
                link_type = path.stem
                if link_type not in self.schema.linkTypes:
                    continue
                for row in _read_jsonl(path):
                    rec = LinkRecord(
                        linkType=link_type,
                        fromType=row["fromType"], fromPk=row["from"],
                        toType=row["toType"], toPk=row["to"],
                        props=row.get("props", {}),
                    )
                    key = (link_type, rec.fromType, rec.fromPk, rec.toType, rec.toPk)
                    if row.get(TOMBSTONE):
                        seen.pop(key, None)
                    else:
                        seen[key] = rec
        self._links_from_portfolio(seen)
        for rec in seen.values():
            self._index_link(rec)
        return self

    def _iter_layers(self) -> list[str]:
        layers = list(LAYERS)
        if self.overlay_dir:
            layers.append("overlay")
        return layers

    def _layer_dir(self, layer: str) -> Path:
        if layer == "overlay":
            assert self.overlay_dir, "overlay_dir 미설정"
            return self.overlay_dir
        return self.data_dir / layer

    def _index_link(self, rec: LinkRecord) -> None:
        self._links[rec.linkType].append(rec)
        self._out_idx[(rec.fromType, rec.fromPk)][rec.linkType].append(rec)
        self._in_idx[(rec.toType, rec.toPk)][rec.linkType].append(rec)

    # ------------------------------------------------- portfolio.json 어댑터

    def _portfolio_path(self) -> Path:
        # overlay에 portfolio.json 이 있으면 그것이 우선 (시나리오 fork)
        if self.overlay_dir and (self.overlay_dir / "portfolio.json").exists():
            return self.overlay_dir / "portfolio.json"
        return self.data_dir / "writeback" / "portfolio.json"

    def _load_portfolio_writeback(self) -> None:
        path = self._portfolio_path()
        if not path.exists():
            return
        doc = json.loads(path.read_text(encoding="utf-8"))
        pf = doc.get("portfolio", {})
        pf_id = pf.get("portfolioId", "main")
        wb = self._layer_objects["writeback"]
        wb["Portfolio"][pf_id] = {**wb["Portfolio"].get(pf_id, {}), **pf}
        for pos in doc.get("positions", []):
            pos_id = f"{pf_id}:{pos['instrumentId']}"
            wb["Position"][pos_id] = {
                "positionId": pos_id, "portfolioId": pf_id, **pos,
            }

    def _links_from_portfolio(self, seen: dict[tuple, LinkRecord]) -> None:
        """portfolio.json 파생 링크: portfolioPositions, positionInstrument."""
        for pk, pos in self._layer_objects["writeback"].get("Position", {}).items():
            pf_id, inst_id = pos["portfolioId"], pos["instrumentId"]
            for link_type, ft, fp, tt, tp in (
                ("portfolioPositions", "Portfolio", pf_id, "Position", pk),
                ("positionInstrument", "Position", pk, "Instrument", inst_id),
            ):
                key = (link_type, ft, fp, tt, tp)
                seen.setdefault(key, LinkRecord(link_type, ft, fp, tt, tp))

    # ---------------------------------------------------------------- reads

    def get(self, object_type: str, pk: str) -> Optional[dict]:
        for t in self.schema.resolve_types(object_type):
            obj = self._objects.get(t, {}).get(pk)
            if obj is not None:
                return obj
        return None

    def get_type_of(self, pk: str, candidates: Iterable[str]) -> Optional[str]:
        for t in candidates:
            if pk in self._objects.get(t, {}):
                return t
        return None

    def query(
        self,
        object_type: str,
        where: dict | None = None,
        predicate: Callable[[dict], bool] | None = None,
        limit: int | None = None,
        order_by: str | None = None,
        descending: bool = True,
    ) -> list[dict]:
        results: list[dict] = []
        for t in self.schema.resolve_types(object_type):
            for obj in self._objects.get(t, {}).values():
                if where and any(obj.get(k) != v for k, v in where.items()):
                    continue
                if predicate and not predicate(obj):
                    continue
                results.append(obj)
        if order_by:
            results.sort(key=lambda o: (o.get(order_by) is None, o.get(order_by)), reverse=descending)
        return results[:limit] if limit else results

    def count(self, object_type: str) -> int:
        return sum(len(self._objects.get(t, {})) for t in self.schema.resolve_types(object_type))

    def neighbors(
        self,
        object_type: str,
        pk: str,
        link_type: str | None = None,
        direction: str = "out",
    ) -> list[Neighbor]:
        """링크 순회. direction: out(정방향) | in(역방향) | both."""
        out: list[Neighbor] = []
        types = self.schema.resolve_types(object_type)
        actual = self.get_type_of(pk, types)
        if actual is None:
            return out
        if direction in ("out", "both"):
            for lt, recs in self._out_idx.get((actual, pk), {}).items():
                if link_type and lt != link_type:
                    continue
                for rec in recs:
                    obj = self._objects.get(rec.toType, {}).get(rec.toPk)
                    if obj is not None:
                        out.append(Neighbor(rec.toType, rec.toPk, obj, rec))
        if direction in ("in", "both"):
            for lt, recs in self._in_idx.get((actual, pk), {}).items():
                if link_type and lt != link_type:
                    continue
                for rec in recs:
                    obj = self._objects.get(rec.fromType, {}).get(rec.fromPk)
                    if obj is not None:
                        out.append(Neighbor(rec.fromType, rec.fromPk, obj, rec))
        return out

    def traverse(self, object_type: str, pk: str, path: list[str]) -> list[list[Neighbor]]:
        """링크 타입 시퀀스를 따라 경로 열거. 스텝 앞에 '<' 를 붙이면 역방향.

        예: Event 에서 포트폴리오까지:
            traverse("DisclosureEvent", eid,
                     ["eventAffectsInstrument", "<positionInstrument", "<portfolioPositions"])
        """
        frontier: list[tuple[str, str, list[Neighbor]]] = [(object_type, pk, [])]
        for step in path:
            direction = "in" if step.startswith("<") else "out"
            lt = step.lstrip("<")
            next_frontier: list[tuple[str, str, list[Neighbor]]] = []
            for otype, opk, trail in frontier:
                for nb in self.neighbors(otype, opk, link_type=lt, direction=direction):
                    next_frontier.append((nb.objectType, nb.pk, trail + [nb]))
            frontier = next_frontier
        return [trail for _, _, trail in frontier]

    def links(self, link_type: str) -> list[LinkRecord]:
        return list(self._links.get(link_type, []))

    # --------------------------------------------------------------- writes

    def _check_ownership(self, layer: str, object_type: str, props: dict) -> None:
        if layer == "overlay":
            return  # 샌드박스는 소유권 검사 면제
        defs = self.schema.objectTypes[object_type].properties
        for name in props:
            d = defs.get(name)
            if d is None or d.owner is None:
                continue
            if d.owner == "USER" and layer != "writeback":
                raise PermissionError(f"{object_type}.{name} 은 USER 소유 — writeback 계층에서만 쓸 수 있음")
            if d.owner == "PIPELINE" and layer == "writeback":
                raise PermissionError(f"{object_type}.{name} 은 PIPELINE 소유 — writeback 계층에서 쓸 수 없음")

    def _validate(self, object_type: str, props: dict) -> None:
        ot = self.schema.objectTypes.get(object_type)
        if ot is None:
            raise KeyError(f"알 수 없는 오브젝트 타입: {object_type}")
        if props.get(ot.primaryKey) in (None, ""):
            raise ValueError(f"{object_type}: primaryKey '{ot.primaryKey}' 누락")
        for name, value in props.items():
            d = ot.properties.get(name)
            if d is None:
                raise ValueError(f"{object_type}.{name}: 스키마에 없는 속성")
            if value is not None and d.enum and value not in d.enum:
                raise ValueError(f"{object_type}.{name}: '{value}' 는 enum {d.enum} 에 없음")

    def replace_objects(self, layer: str, object_type: str, objects: list[dict]) -> None:
        """(layer, type) 스냅샷 전체 교체 — 파이프라인 스테이지용."""
        pk_field = self.schema.objectTypes[object_type].primaryKey
        for obj in objects:
            self._validate(object_type, obj)
            self._check_ownership(layer, object_type, obj)
        _write_jsonl(
            self._layer_dir(layer) / "objects" / f"{object_type}.jsonl",
            sorted(objects, key=lambda o: str(o[pk_field])),
        )

    def append_object(self, layer: str, object_type: str, obj: dict) -> None:
        """단일 upsert (append-only, 로드 시 last-wins) — 액션/writeback용."""
        self._validate(object_type, obj)
        self._check_ownership(layer, object_type, obj)
        _append_jsonl(self._layer_dir(layer) / "objects" / f"{object_type}.jsonl", obj)
        pk = obj[self.schema.objectTypes[object_type].primaryKey]
        merged = self._objects[object_type].get(pk, {})
        merged.update(obj)
        self._objects[object_type][pk] = merged
        if layer in self._layer_objects:
            self._layer_objects[layer][object_type][pk] = obj

    def delete_object(self, layer: str, object_type: str, pk: str) -> None:
        pk_field = self.schema.objectTypes[object_type].primaryKey
        _append_jsonl(
            self._layer_dir(layer) / "objects" / f"{object_type}.jsonl",
            {pk_field: pk, TOMBSTONE: True},
        )
        self._objects.get(object_type, {}).pop(pk, None)

    def replace_links(self, layer: str, link_type: str, links: list[LinkRecord]) -> None:
        if link_type not in self.schema.linkTypes:
            raise KeyError(f"알 수 없는 링크 타입: {link_type}")
        _write_jsonl(
            self._layer_dir(layer) / "links" / f"{link_type}.jsonl",
            [l.to_json() for l in sorted(links, key=lambda l: (l.fromPk, l.toPk))],
        )

    def append_link(self, layer: str, rec: LinkRecord) -> None:
        if rec.linkType not in self.schema.linkTypes:
            raise KeyError(f"알 수 없는 링크 타입: {rec.linkType}")
        _append_jsonl(self._layer_dir(layer) / "links" / f"{rec.linkType}.jsonl", rec.to_json())
        self._index_link(rec)

    # ------------------------------------------------------------ portfolio

    def read_portfolio_doc(self) -> dict:
        return json.loads(self._portfolio_path().read_text(encoding="utf-8"))

    def write_portfolio_doc(self, doc: dict, overlay: bool = False) -> None:
        """portfolio.json 원자적 교체. overlay=True 면 시나리오 샌드박스에 기록."""
        if overlay:
            assert self.overlay_dir, "overlay_dir 미설정"
            path = self.overlay_dir / "portfolio.json"
        else:
            path = self.data_dir / "writeback" / "portfolio.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
