"""OntoQuant MCP 서버 — Claude Code 가 온톨로지를 조회하고 액션을 수행하는 표면.

실행: python -m onto_mcp.server  (stdio)
등록: 레포 루트 .mcp.json 참조.

설계 원칙:
- 조회 도구는 자유롭게, 상태 변경은 반드시 ActionEngine(submission criteria) 경유
- criteria 실패 시 failureMessage 배열을 그대로 반환 — Claude 가 사용자에게 설명
- publish 는 데이터/산출물 커밋+푸시 → GitHub Actions 재배포 트리거
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from ontoquant import config
from ontoquant.core.actions import ActionEngine
from ontoquant.core.store import OntologyStore

mcp = FastMCP("ontoquant")

ACTOR = "claude-mcp"


def _store() -> OntologyStore:
    return OntologyStore().build()


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


# ---------------------------------------------------------------- 조회

@mcp.tool()
def query_objects(objectType: str, where: dict | None = None, limit: int = 20) -> str:
    """온톨로지 오브젝트 조회. objectType 은 구체 타입 또는 인터페이스(Event 등).
    where 는 속성 동등 필터 (예: {"market": "KRX"})."""
    rows = _store().query(objectType, where=where, limit=limit)
    return _json({"count": len(rows), "objects": rows})


@mcp.tool()
def get_object(objectType: str, pk: str) -> str:
    """단일 오브젝트 + 연결 링크 요약 (Object View)."""
    store = _store()
    obj = store.get(objectType, pk)
    if obj is None:
        return _json({"error": f"{objectType}:{pk} 없음"})
    links: dict[str, list] = {}
    for nb in store.neighbors(objectType, pk, direction="both"):
        links.setdefault(nb.link.linkType, []).append(
            {"objectType": nb.objectType, "pk": nb.pk,
             "title": nb.obj.get(store.schema.objectTypes[nb.objectType].titleProperty),
             **({"props": nb.link.props} if nb.link.props else {})})
    return _json({"object": obj, "links": {k: v[:20] for k, v in links.items()}})


@mcp.tool()
def traverse_graph(objectType: str, pk: str, path: list[str]) -> str:
    """링크 타입 시퀀스로 그래프 순회. '<' 접두사 = 역방향.
    예: DisclosureEvent 에서 포트폴리오까지:
    ["eventAffectsInstrument", "<positionInstrument", "<portfolioPositions"]"""
    store = _store()
    paths = store.traverse(objectType, pk, path)
    return _json({"count": len(paths), "paths": [
        [{"objectType": nb.objectType, "pk": nb.pk} for nb in p] for p in paths[:30]]})


@mcp.tool()
def get_event_propagation(eventId: str) -> str:
    """이벤트의 포트폴리오 전파 리포트 (경로/점수/상위 포지션)."""
    impacts_path = config.COMPUTED_DIR / "impacts.json"
    if impacts_path.exists():
        impacts = json.loads(impacts_path.read_text(encoding="utf-8"))
        if eventId in impacts:
            return _json(impacts[eventId])
    return _json({"error": f"전파 리포트 없음: {eventId} (propagation 스테이지 실행 필요)"})


@mcp.tool()
def search_similar_events(query: str, topK: int = 8) -> str:
    """임베딩 RAG — 과거 공시/뉴스/이벤트를 의미 검색. 각 결과에 해당 타입의
    이벤트 스터디 CAR 요약을 동봉한다 (인사이트 서사 작성용)."""
    from ontoquant.events import embed as emb
    from ontoquant.insights.event_study import get_type_summary
    if not emb.available():
        return _json({"error": "sentence-transformers 미설치"})
    store = _store()
    index = emb.EmbeddingIndex()
    results = []
    for eid, score in index.search_text(query, top_k=topK):
        e = store.get("Event", eid)
        if not e:
            continue
        car = get_type_summary(store, e["eventType"], e.get("market"))
        results.append({"eventId": eid, "similarity": round(score, 3),
                        "title": e["title"], "eventType": e["eventType"],
                        "occurredAt": e.get("occurredAt"), "severity": e.get("severity"),
                        "carStudy": car})
    return _json({"query": query, "results": results})


@mcp.tool()
def get_portfolio_summary() -> str:
    """포트폴리오 요약: 평가액, 포지션, 비중, 한도."""
    store = _store()
    pf = store.query("Portfolio")[0]
    positions = []
    for p in sorted(store.query("Position"), key=lambda x: -(x.get("marketValueBase") or 0)):
        inst = store.get("Instrument", p["instrumentId"]) or {}
        positions.append({**p, "name": inst.get("nameKo") or inst.get("name")})
    return _json({"portfolio": pf, "positions": positions})


@mcp.tool()
def get_risk_metrics() -> str:
    """최신 리스크 지표 (VaR/변동성/MDD/HHI/베타 + 포지션 기여)."""
    return _json(_store().query("RiskMetric"))


@mcp.tool()
def get_insights(validationStatus: str | None = None) -> str:
    """인사이트 목록. validationStatus 로 필터 가능 (VALIDATED/UNVALIDATED/REJECTED)."""
    where = {"validationStatus": validationStatus} if validationStatus else None
    return _json(_store().query("Insight", where=where))


@mcp.tool()
def list_actions() -> str:
    """수행 가능한 액션 타입과 파라미터/제출 기준."""
    schema = _store().schema
    return _json({
        name: {
            "displayName": at.displayName, "description": at.description,
            "parameters": {k: {"type": p.type, "required": p.required,
                               "enum": p.enum, "objectType": p.objectType}
                           for k, p in at.parameters.items()},
            "submissionCriteria": [c.failureMessage for c in at.submissionCriteria],
        } for name, at in schema.actionTypes.items()})


# ---------------------------------------------------------------- 액션 (kinetic)

@mcp.tool()
def submit_action(actionApiName: str, params: dict) -> str:
    """액션 제출 — submission criteria 검증 후 규칙 실행 + 감사 로그.
    실패 시 failures 배열이 반환된다."""
    engine = ActionEngine(_store(), actor=ACTOR)
    try:
        return _json(engine.submit(actionApiName, params))
    except (ValueError, KeyError) as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def propose_rebalance(title: str, legs: list[dict], rationale: str,
                      strategyRule: dict | None = None,
                      insightIds: list[str] | None = None) -> str:
    """리밸런싱 제안 생성 + vectorbt 백테스트 검증 (게이트 통과 시 PENDING).
    legs: [{instrumentId, side: BUY|SELL|HOLD, targetWeightDelta, reason?}]"""
    engine = ActionEngine(_store(), actor=ACTOR)
    try:
        result = engine.submit("proposeRebalance", {
            "portfolioId": "main", "title": title, "legs": legs,
            "rationale": rationale, "strategyRule": strategyRule,
            "insightIds": insightIds or []})
    except (ValueError, KeyError) as exc:
        return _json({"ok": False, "error": str(exc)})
    if result.get("ok"):
        store = _store()
        pid = result["created"].get("RebalanceProposal")
        prop = store.get("RebalanceProposal", pid) or {}
        run = store.get("EvaluationRun", prop.get("backtestRunId") or "")
        result["proposal"] = prop
        result["backtest"] = run
    return _json(result)


@mcp.tool()
def record_decision(proposalId: str, decision: str, reason: str) -> str:
    """제안 결재 (APPROVE/REJECT) — Decision 캡처 + 승인 시 portfolio.json writeback."""
    engine = ActionEngine(_store(), actor=ACTOR)
    try:
        return _json(engine.submit("approveProposal", {
            "proposalId": proposalId, "decision": decision, "reason": reason}))
    except (ValueError, KeyError) as exc:
        return _json({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------- 시나리오

@mcp.tool()
def run_scenario(name: str) -> str:
    """시나리오 fork 생성 (온톨로지 샌드박스). 이후 scenario_apply 로 액션 적용."""
    from ontoquant.scenario import sandbox
    scenario_id = sandbox.fork(name, actor=ACTOR)
    return _json({"ok": True, "scenarioId": scenario_id,
                  "next": "scenario_apply → compare_scenario → commit_scenario/discard_scenario"})


@mcp.tool()
def scenario_apply(scenarioId: str, actionApiName: str, params: dict) -> str:
    """샌드박스에 액션 적용 (원본 온톨로지 무변경)."""
    from ontoquant.scenario import sandbox
    try:
        return _json(sandbox.apply_action(scenarioId, actionApiName, params, actor=ACTOR))
    except (ValueError, KeyError, FileNotFoundError) as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def compare_scenario(scenarioId: str) -> str:
    """시나리오 vs 베이스라인 diff (VaR/변동성/MDD/HHI, 포지션, 비중)."""
    from ontoquant.scenario import sandbox
    try:
        return _json(sandbox.compare(scenarioId))
    except FileNotFoundError as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def commit_scenario(scenarioId: str) -> str:
    """시나리오 변경을 본 온톨로지 writeback 에 병합."""
    from ontoquant.scenario import sandbox
    try:
        return _json(sandbox.commit(scenarioId, actor=ACTOR))
    except (ValueError, FileNotFoundError) as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def discard_scenario(scenarioId: str) -> str:
    """시나리오 폐기 (오버레이는 감사용 보존)."""
    from ontoquant.scenario import sandbox
    try:
        return _json(sandbox.discard(scenarioId))
    except FileNotFoundError as exc:
        return _json({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------- 운영

@mcp.tool()
def run_pipeline(stages: str = "compute,propagation,insights,proposals,export") -> str:
    """파이프라인 스테이지 실행 (콤마 구분). 전체: 'all'."""
    proc = subprocess.run(
        [sys.executable, "-m", "ontoquant.run_daily", "--stage", stages],
        capture_output=True, text=True, timeout=1800, cwd=str(config.ROOT))
    return _json({"exitCode": proc.returncode,
                  "stdout": proc.stdout[-3000:], "stderr": proc.stderr[-1500:]})


@mcp.tool()
def publish(message: str = "chore: 온톨로지 데이터 갱신") -> str:
    """데이터/대시보드 산출물을 git 커밋 + 푸시 → GitHub Actions 재배포 트리거.
    주의: 원격(origin)이 설정된 경우에만 푸시된다."""
    root = str(config.ROOT)
    cmds = [
        ["git", "add", "data", "dashboard/public/data"],
        ["git", "commit", "-m", f"{message}\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>"],
        ["git", "push"],
    ]
    log = []
    for cmd in cmds:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=root, timeout=120)
        log.append({"cmd": " ".join(cmd), "exit": proc.returncode,
                    "out": (proc.stdout + proc.stderr)[-400:]})
        if proc.returncode != 0 and cmd[1] != "commit":  # commit 은 '변경 없음' 허용
            break
    return _json({"log": log})


if __name__ == "__main__":
    mcp.run()
