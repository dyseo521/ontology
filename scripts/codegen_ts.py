#!/usr/bin/env python3
"""YAML 온톨로지 스키마 → TypeScript 타입 + 대시보드용 schema.json 생성.

사용:
  python scripts/codegen_ts.py          # 생성
  python scripts/codegen_ts.py --check  # 드리프트 검사 (CI)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from ontoquant.core.schema import PropertyDef, load_schema  # noqa: E402

TS_PATH = ROOT / "dashboard" / "src" / "lib" / "ontology-types.ts"
SCHEMA_JSON_PATH = ROOT / "dashboard" / "public" / "data" / "schema.json"

TS_SCALARS = {
    "string": "string", "integer": "number", "double": "number",
    "boolean": "boolean", "date": "string", "timestamp": "string", "json": "unknown",
}


def ts_type(p: PropertyDef) -> str:
    if p.enum:
        return " | ".join(f'"{v}"' for v in p.enum)
    if p.type == "array":
        inner = ts_type(p.items) if p.items else "unknown"
        return f"({inner})[]" if "|" in inner or " " in inner else f"{inner}[]"
    if p.type == "struct":
        if not p.fields:
            return "Record<string, unknown>"
        fields = "; ".join(
            f"{name}{'?' if fd.nullable else ''}: {ts_type(fd)}" for name, fd in p.fields.items()
        )
        return "{ " + fields + " }"
    return TS_SCALARS.get(p.type, "unknown")


def generate_ts(schema) -> str:
    out = [
        "// 자동 생성 파일 — 편집 금지. 원천: ontology/*.yaml",
        "// 재생성: python scripts/codegen_ts.py",
        "",
    ]
    for name, ot in sorted(schema.objectTypes.items()):
        out.append(f"/** {ot.displayName} — {ot.description or ''} */")
        out.append(f"export interface {name} {{")
        for prop_name, p in ot.properties.items():
            opt = "?" if p.nullable else ""
            out.append(f"  {prop_name}{opt}: {ts_type(p)};")
        out.append("}")
        out.append("")
    for name, iface in sorted(schema.interfaces.items()):
        impls = " | ".join(iface.implementedBy)
        out.append(f"/** 인터페이스 {iface.displayName} */")
        out.append(f"export type {name} = {impls};")
        out.append("")
    link_names = " | ".join(f'"{n}"' for n in sorted(schema.linkTypes))
    obj_names = " | ".join(f'"{n}"' for n in sorted(schema.objectTypes))
    out.append(f"export type LinkTypeName = {link_names};")
    out.append(f"export type ObjectTypeName = {obj_names};")
    out.append("")
    return "\n".join(out)


def generate_schema_json(schema) -> str:
    doc = {
        "objectTypes": [
            {
                "apiName": ot.apiName,
                "displayName": ot.displayName,
                "description": ot.description,
                "icon": ot.icon,
                "color": ot.color,
                "status": ot.status,
                "primaryKey": ot.primaryKey,
                "titleProperty": ot.titleProperty,
                "implements": ot.implements,
            }
            for ot in sorted(schema.objectTypes.values(), key=lambda o: o.apiName)
        ],
        "interfaces": [
            {
                "apiName": i.apiName,
                "displayName": i.displayName,
                "color": i.color,
                "implementedBy": i.implementedBy,
            }
            for i in sorted(schema.interfaces.values(), key=lambda i: i.apiName)
        ],
        "linkTypes": [
            {
                "apiName": lt.apiName,
                "displayName": lt.displayName,
                "from": lt.from_,
                "to": lt.to,
                "cardinality": lt.cardinality,
            }
            for lt in sorted(schema.linkTypes.values(), key=lambda l: l.apiName)
        ],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    schema = load_schema(ROOT / "ontology")
    ts, sj = generate_ts(schema), generate_schema_json(schema)

    if args.check:
        drift = []
        if not TS_PATH.exists() or TS_PATH.read_text(encoding="utf-8") != ts:
            drift.append(str(TS_PATH))
        if not SCHEMA_JSON_PATH.exists() or SCHEMA_JSON_PATH.read_text(encoding="utf-8") != sj:
            drift.append(str(SCHEMA_JSON_PATH))
        if drift:
            print("codegen 드리프트 감지 — `python scripts/codegen_ts.py` 재실행 필요:")
            for d in drift:
                print(f"  {d}")
            sys.exit(1)
        print("codegen: 드리프트 없음")
        return

    TS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    TS_PATH.write_text(ts, encoding="utf-8")
    SCHEMA_JSON_PATH.write_text(sj, encoding="utf-8")
    print(f"codegen: {TS_PATH.relative_to(ROOT)}, {SCHEMA_JSON_PATH.relative_to(ROOT)} 생성")


if __name__ == "__main__":
    main()
