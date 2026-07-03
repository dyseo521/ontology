"""간단 CLI — 온톨로지 조회/검증용.

사용:
  python -m ontoquant.cli query Instrument [--where market=KRX] [--limit 5]
  python -m ontoquant.cli get Instrument KRX:005930
  python -m ontoquant.cli neighbors Position main:KRX:005930
  python -m ontoquant.cli counts
"""
from __future__ import annotations

import argparse
import json

from ontoquant.core.store import OntologyStore


def main() -> None:
    ap = argparse.ArgumentParser(prog="ontoquant")
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("query")
    q.add_argument("objectType")
    q.add_argument("--where", action="append", default=[])
    q.add_argument("--limit", type=int, default=20)

    g = sub.add_parser("get")
    g.add_argument("objectType")
    g.add_argument("pk")

    n = sub.add_parser("neighbors")
    n.add_argument("objectType")
    n.add_argument("pk")
    n.add_argument("--link", default=None)
    n.add_argument("--direction", default="both")

    sub.add_parser("counts")

    args = ap.parse_args()
    store = OntologyStore().build()

    if args.cmd == "query":
        where = dict(w.split("=", 1) for w in args.where) or None
        rows = store.query(args.objectType, where=where, limit=args.limit)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        print(f"-- {len(rows)}건")
    elif args.cmd == "get":
        print(json.dumps(store.get(args.objectType, args.pk), ensure_ascii=False, indent=2))
    elif args.cmd == "neighbors":
        for nb in store.neighbors(args.objectType, args.pk, link_type=args.link, direction=args.direction):
            print(f"[{nb.link.linkType}] {nb.objectType}:{nb.pk}")
    elif args.cmd == "counts":
        for t in sorted(store.schema.objectTypes):
            c = store.count(t)
            if c:
                print(f"{t:24s} {c}")


if __name__ == "__main__":
    main()
