"""일일 파이프라인 오케스트레이터.

  python -m ontoquant.run_daily --stage all
  python -m ontoquant.run_daily --stage ingest,compute,export

스테이지: ingest → compute → events → propagation → insights → proposals → export
부분 실패 허용: 소스 하나가 죽어도 계속 진행, 상태는 meta.json 에 기록.
스테이지 간 store 재구성(빌드)으로 파일 계층 변경을 반영한다 (<1s).
"""
from __future__ import annotations

import argparse
import time
import traceback

from ontoquant.core.store import OntologyStore

ALL_STAGES = ["ingest", "compute", "events", "propagation", "insights", "proposals", "export"]


def stage_ingest(statuses: dict) -> None:
    from ontoquant import seed
    from ontoquant.ingest import fred, kenfrench, prices_kr, prices_us

    seed.run()  # universe.yaml → Instrument/Factor 스냅샷 (idempotent)
    store = OntologyStore().build()
    for name, mod in (("prices_kr", prices_kr), ("prices_us", prices_us),
                      ("fred", fred), ("kenfrench", kenfrench)):
        try:
            results = mod.run(store)
            errors = [r for r in results if str(r.get("status", "")).startswith("error")]
            added = sum(r.get("added", 0) for r in results)
            statuses[name] = {"status": "partial" if errors else "ok",
                              "added": added, "errors": [e["status"] for e in errors][:3]}
        except Exception as exc:  # noqa: BLE001
            statuses[name] = {"status": f"failed: {exc}"}
    from ontoquant.ingest import company, dart, edgar, fundamentals, news_kr, press_rss, rss
    store = OntologyStore().build()
    for name, mod in (("dart", dart), ("edgar", edgar), ("news_kr", news_kr),
                      ("press_rss", press_rss), ("rss", rss),
                      ("company", company), ("fundamentals", fundamentals)):
        try:
            statuses[name] = mod.run(store)
        except Exception as exc:  # noqa: BLE001
            statuses[name] = {"status": f"failed: {exc}"}


def stage_compute(statuses: dict) -> None:
    from ontoquant.compute import factor_model, risk

    store = OntologyStore().build()
    statuses["risk"] = risk.run(store)
    store = OntologyStore().build()
    statuses["factor_model"] = factor_model.run(store)


def stage_events(statuses: dict) -> None:
    try:
        from ontoquant.events import process
    except ImportError:
        statuses["events"] = {"status": "not-implemented (Phase 2)"}
        return
    store = OntologyStore().build()
    statuses["events"] = process.run(store)


def stage_propagation(statuses: dict) -> None:
    try:
        from ontoquant.propagation import impact
    except ImportError:
        statuses["propagation"] = {"status": "not-implemented (Phase 2)"}
        return
    store = OntologyStore().build()
    statuses["propagation"] = impact.run(store)


def stage_insights(statuses: dict) -> None:
    from ontoquant.insights import event_study, rules

    store = OntologyStore().build()
    as_of = statuses.get("risk", {}).get("asOf") or ""
    try:
        es = event_study.run(store, as_of or None)
        statuses["event_study"] = {"status": "ok", "types": es["types"],
                                   "significant": len(es["significant"])}
        store = OntologyStore().build()
    except Exception as exc:  # noqa: BLE001
        statuses["event_study"] = {"status": f"failed: {exc}"}
    extra = None
    try:
        from ontoquant.insights import event_rules
        extra = event_rules.build(store, as_of)
    except ImportError:
        pass
    statuses["insights"] = rules.run(store, as_of, extra=extra)


def stage_proposals(statuses: dict) -> None:
    from ontoquant.proposals import outcomes, rebalance

    store = OntologyStore().build()
    statuses["proposals"] = rebalance.run(store)
    store = OntologyStore().build()
    statuses["decision_outcomes"] = outcomes.run(store)


def stage_export(statuses: dict) -> None:
    from ontoquant import quality
    from ontoquant.export import artifacts

    store = OntologyStore().build()
    try:
        q = quality.run(store, verbose=False)
        statuses["quality"] = q["summary"]
    except Exception as exc:  # noqa: BLE001
        statuses["quality"] = {"status": f"failed: {exc}"}
    statuses["export"] = artifacts.export_all(store, statuses)


STAGE_FNS = {
    "ingest": stage_ingest,
    "compute": stage_compute,
    "events": stage_events,
    "propagation": stage_propagation,
    "insights": stage_insights,
    "proposals": stage_proposals,
    "export": stage_export,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    help="all 또는 콤마 구분 스테이지 (예: ingest,compute,export)")
    args = ap.parse_args()
    stages = ALL_STAGES if args.stage == "all" else [s.strip() for s in args.stage.split(",")]

    statuses: dict = {}
    for stage in stages:
        if stage not in STAGE_FNS:
            raise SystemExit(f"알 수 없는 스테이지: {stage}")
        t0 = time.time()
        print(f"▶ {stage} ...", flush=True)
        try:
            STAGE_FNS[stage](statuses)
            print(f"  ✓ {stage} ({time.time() - t0:.1f}s): {statuses.get(stage, 'ok')}", flush=True)
        except Exception:  # noqa: BLE001
            print(f"  ✗ {stage} 실패:\n{traceback.format_exc()}", flush=True)
            statuses[stage] = {"status": "failed"}
    print("완료:", {k: (v.get("status", "ok") if isinstance(v, dict) else v)
                   for k, v in statuses.items()})


if __name__ == "__main__":
    main()
